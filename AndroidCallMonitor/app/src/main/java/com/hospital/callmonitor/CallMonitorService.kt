package com.hospital.callmonitor

import android.app.*
import android.content.Context
import android.content.Intent
import android.media.AudioManager
import android.os.Build
import android.os.Bundle
import android.os.IBinder
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.util.Log
import androidx.core.app.NotificationCompat
import org.json.JSONObject
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.util.*
import kotlin.concurrent.thread
import android.telecom.TelecomManager
import android.telephony.SmsManager
import android.content.pm.PackageManager
import android.os.Handler
import android.os.Looper
import android.widget.Toast
import io.socket.client.IO
import io.socket.client.Socket
import javax.net.ssl.*
import java.security.cert.X509Certificate
import java.security.SecureRandom

class CallMonitorService : Service() {

    companion object {
        private const val NOTIFICATION_ID = 888
        private const val CHANNEL_ID = "CallMonitorChannel"
        
        // 用來將日誌傳遞給 MainActivity 的靜態回呼函數
        var logListener: ((String) -> Unit)? = null
        
        fun addLog(msg: String) {
            logListener?.invoke(msg)
        }
    }

    private lateinit var audioManager: AudioManager
    private var speechRecognizer: SpeechRecognizer? = null
    private var isRecognizerActive = false
    private var flaskIpAddress = "192.168.1.100" // 預設 IP，可在 App 畫面修改
    private var mSocket: Socket? = null
    
    // 錄音相關成員變數
    private var mediaRecorder: android.media.MediaRecorder? = null
    private var audioFile: java.io.File? = null
    
    // 來電號碼暫存
    private var currentPhoneNumber: String = "未知"

    private var sslContext: SSLContext? = null
    private val trustAllVerifier = HostnameVerifier { _, _ -> true }

    private fun getUnsafeSSLContext(): SSLContext {
        if (sslContext == null) {
            val trustAllCerts = arrayOf<TrustManager>(object : X509TrustManager {
                override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {}
                override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {}
                override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
            })
            sslContext = SSLContext.getInstance("SSL").apply {
                init(null, trustAllCerts, SecureRandom())
            }
        }
        return sslContext!!
    }

    private fun getBaseUrl(): String {
        val ip = flaskIpAddress.trim()
        return when {
            ip.startsWith("http://") || ip.startsWith("https://") -> {
                if (ip.substringAfter("://").contains(":")) ip else "$ip:5000"
            }
            else -> {
                "https://$ip:5000"
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        audioManager = getSystemService(Context.AUDIO_SERVICE) as AudioManager
        createNotificationChannel()
        startForeground(NOTIFICATION_ID, getServiceNotification("等待電話接通..."))
        
        // 讀取先前儲存的 Flask IP 設定
        val prefs = getSharedPreferences("CallMonitorPrefs", Context.MODE_PRIVATE)
        flaskIpAddress = prefs.getString("flask_ip", "192.168.1.100") ?: "192.168.1.100"

        // 初始化 Socket.IO 連線
        initSocket()

        // 使用 PhoneStateListener 直接註冊電話狀態，這是最穩定可靠的做法 (比起 BroadcastReceiver 更不容易漏訊號)
        val telephonyManager = getSystemService(Context.TELEPHONY_SERVICE) as android.telephony.TelephonyManager
        phoneStateListener = object : android.telephony.PhoneStateListener() {
            override fun onCallStateChanged(state: Int, phoneNumber: String?) {
                super.onCallStateChanged(state, phoneNumber)
                val stateStr = when(state) {
                    android.telephony.TelephonyManager.CALL_STATE_RINGING -> "RINGING"
                    android.telephony.TelephonyManager.CALL_STATE_OFFHOOK -> "OFFHOOK"
                    android.telephony.TelephonyManager.CALL_STATE_IDLE -> "IDLE"
                    else -> "UNKNOWN"
                }
                if (stateStr != "UNKNOWN") {
                    handleCallState(stateStr, phoneNumber)
                }
            }
        }
        telephonyManager.listen(phoneStateListener, android.telephony.PhoneStateListener.LISTEN_CALL_STATE)
    }

    private var phoneStateListener: android.telephony.PhoneStateListener? = null

    override fun onDestroy() {
        super.onDestroy()
        try {
            if (phoneStateListener != null) {
                val telephonyManager = getSystemService(Context.TELEPHONY_SERVICE) as android.telephony.TelephonyManager
                telephonyManager.listen(phoneStateListener, android.telephony.PhoneStateListener.LISTEN_NONE)
            }
        } catch (e: Exception) {}
        stopSpeechRecognition()
        stopAudioRecording()
        mSocket?.disconnect()
    }

    // 移除 TTS 相關初始化函數

    private fun initSocket() {
        try {
            val baseUrl = getBaseUrl()
            val opts = IO.Options().apply {
                forceNew = true
                reconnection = true
                if (baseUrl.startsWith("https://")) {
                    val trustAllCerts = arrayOf<TrustManager>(object : X509TrustManager {
                        override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {}
                        override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {}
                        override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
                    })
                    val builder = okhttp3.OkHttpClient.Builder()
                        .sslSocketFactory(getUnsafeSSLContext().socketFactory, trustAllCerts[0] as X509TrustManager)
                        .hostnameVerifier(trustAllVerifier)
                    val client = builder.build()
                    callFactory = client
                    webSocketFactory = client
                }
            }
            mSocket = IO.socket(baseUrl, opts)
            
            mSocket?.on(Socket.EVENT_CONNECT) {
                Log.d("CallMonitorService", "Socket.IO connected")
                mSocket?.emit("register_android")
            }
            
            mSocket?.on(Socket.EVENT_DISCONNECT) {
                Log.d("CallMonitorService", "Socket.IO disconnected")
            }
            
            mSocket?.on("send_sms") { args ->
                if (args.isNotEmpty() && args[0] is JSONObject) {
                    val data = args[0] as JSONObject
                    val phone = data.optString("phone")
                    val message = data.optString("message")
                    Log.d("CallMonitorService", "Received send_sms request: phone=$phone, message=$message")
                    if (phone.isNotEmpty() && message.isNotEmpty()) {
                        sendSms(phone, message)
                    }
                }
            }
            
            mSocket?.connect()
        } catch (e: Exception) {
            Log.e("CallMonitorService", "Failed to initialize Socket.IO: ${e.message}")
        }
    }

    private fun sendSms(phone: String, message: String) {
        try {
            if (androidx.core.content.ContextCompat.checkSelfPermission(this, android.Manifest.permission.SEND_SMS) == PackageManager.PERMISSION_GRANTED) {
                val smsManager = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                    getSystemService(SmsManager::class.java)
                } else {
                    @Suppress("DEPRECATION")
                    SmsManager.getDefault()
                }
                smsManager.sendTextMessage(phone, null, message, null, null)
                Log.d("CallMonitorService", "SMS sent successfully to $phone")
            } else {
                Log.e("CallMonitorService", "Cannot send SMS: SEND_SMS permission not granted")
            }
        } catch (e: Exception) {
            Log.e("CallMonitorService", "Error sending SMS: ${e.message}")
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val initialCallState = intent?.getStringExtra("call_state") ?: "IDLE"
        if (initialCallState != "IDLE") {
            handleCallState(initialCallState, intent?.getStringExtra("phone_number"))
        }
        return START_STICKY
    }

    private fun handleCallState(callState: String, phoneNumber: String?) {
        if (phoneNumber != null && phoneNumber != "未知" && phoneNumber.isNotEmpty()) {
            currentPhoneNumber = phoneNumber
        }

        Log.d("CallMonitorService", "服務收到命令狀態: $callState, 號碼: $currentPhoneNumber")

        when (callState) {
            "RINGING" -> {
                updateNotification("來電響鈴中: $currentPhoneNumber")
                val timeStr = java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.getDefault()).format(java.util.Date())
                addLog("[$timeStr] 偵測到來電響鈴: $currentPhoneNumber\n")
                
                // 自動接聽來電 (延遲 1.5 秒以確保系統通話狀態完全就緒)
                thread {
                    try {
                        Thread.sleep(1500)
                        val telecomManager = getSystemService(Context.TELECOM_SERVICE) as TelecomManager
                        if (androidx.core.content.ContextCompat.checkSelfPermission(this@CallMonitorService, android.Manifest.permission.ANSWER_PHONE_CALLS) == PackageManager.PERMISSION_GRANTED) {
                            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                                telecomManager.acceptRingingCall()
                                Log.d("CallMonitorService", "✅ 已自動接聽來電: $phoneNumber")
                            } else {
                                Log.w("CallMonitorService", "SDK 版本低於 Oreo (26)，不支援 acceptRingingCall()")
                            }
                        } else {
                            Log.e("CallMonitorService", "未獲得 ANSWER_PHONE_CALLS 權限，無法自動接聽！")
                        }
                    } catch (e: Exception) {
                        Log.e("CallMonitorService", "自動接聽來電時發生錯誤: ${e.message}")
                    }
                }
            }
            "OFFHOOK" -> {
                updateNotification("通話進行中 - 正在監聽語音")
                val timeStr = java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.getDefault()).format(java.util.Date())
                addLog("[$timeStr] 電話已接通，啟動語音辨識...\n")
                
                // 必須開啟擴音，Android 系統才允許麥克風側錄通話對方的聲音
                audioManager.mode = AudioManager.MODE_IN_COMMUNICATION
                audioManager.isSpeakerphoneOn = true
                
                // 接通後啟動語音辨識與錄音
                startSpeechRecognition()
                Handler(Looper.getMainLooper()).postDelayed({
                    startAudioRecording()
                }, 1500)
            }
            "IDLE" -> {
                updateNotification("通話結束 - 語音監聽暫停")
                val timeStr = java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.getDefault()).format(java.util.Date())
                addLog("[$timeStr] 通話結束，停止辨識\n---\n")
                
                // 恢復一般音訊設定
                audioManager.mode = AudioManager.MODE_NORMAL
                audioManager.isSpeakerphoneOn = false
                
                // 1. 停止語音辨識
                stopSpeechRecognition()
                // 2. 結束錄音並上傳
                stopAudioRecording()
            }
        }
    }

    // 啟動語音辨識
    private fun startSpeechRecognition() {
        if (isRecognizerActive) return

        android.os.Handler(android.os.Looper.getMainLooper()).post {
            try {
                if (speechRecognizer == null) {
                    speechRecognizer = SpeechRecognizer.createSpeechRecognizer(this@CallMonitorService)
                }
                
                val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE, "zh-TW") // 強制使用繁體中文
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, "zh-TW")
                    putExtra(RecognizerIntent.EXTRA_ONLY_RETURN_LANGUAGE_PREFERENCE, "zh-TW")
                    putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false) // 只取得完整句子
                }

                speechRecognizer?.setRecognitionListener(object : RecognitionListener {
                    override fun onReadyForSpeech(params: Bundle?) {
                        Log.d("SpeechRecognizer", "準備好聆聽對話...")
                        isRecognizerActive = true
                        
                        val timeStr = java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.getDefault()).format(java.util.Date())
                        addLog("[$timeStr] 麥克風已就緒，開始收音...\n")
                    }
                    override fun onBeginningOfSpeech() {}
                    override fun onRmsChanged(rmsdB: Float) {}
                    override fun onBufferReceived(buffer: ByteArray?) {}
                    override fun onEndOfSpeech() {}
                    
                    override fun onError(error: Int) {
                        val errorDesc = when(error) {
                            SpeechRecognizer.ERROR_AUDIO -> "音訊錄製錯誤"
                            SpeechRecognizer.ERROR_CLIENT -> "客戶端錯誤"
                            SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "權限不足"
                            SpeechRecognizer.ERROR_NETWORK -> "網路錯誤"
                            SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "網路超時"
                            SpeechRecognizer.ERROR_NO_MATCH -> "聽不懂/無配對"
                            SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "辨識器忙碌"
                            SpeechRecognizer.ERROR_SERVER -> "伺服器錯誤"
                            SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "沒講話/超時"
                            else -> "未知錯誤"
                        }
                        Log.e("SpeechRecognizer", "辨識錯誤碼: $error ($errorDesc)")
                        
                        val timeStr = java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.getDefault()).format(java.util.Date())
                        addLog("[$timeStr] 辨識暫停 ($errorDesc)\n---\n")
                        
                        isRecognizerActive = false
                        // 失敗後，如果仍在監聽狀態，延遲重試
                        Handler(Looper.getMainLooper()).postDelayed({
                            startSpeechRecognition()
                        }, 1000)
                    }

                    override fun onResults(results: Bundle?) {
                        isRecognizerActive = false
                        val matches = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                        if (!matches.isNullOrEmpty()) {
                            val recognizedText = matches[0]
                            Log.d("SpeechRecognizer", "🎙️ 通話辨識文本: $recognizedText")
                            
                            val timeStr = java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.getDefault()).format(java.util.Date())
                            val logMsg = "[$timeStr] 來電: $currentPhoneNumber\n辨識內容: $recognizedText\n---\n"
                            
                            addLog(logMsg)
                            
                            Handler(Looper.getMainLooper()).post {
                                Toast.makeText(applicationContext, "辨識到: $recognizedText", Toast.LENGTH_SHORT).show()
                            }
                            sendTextToFlask(recognizedText, currentPhoneNumber)
                        }

                        // 持續監聽
                        startSpeechRecognition()
                    }

                    override fun onPartialResults(partialResults: Bundle?) {}
                    override fun onEvent(eventType: Int, params: Bundle?) {}
                })

                speechRecognizer?.startListening(intent)
                Log.d("CallMonitorService", "已成功啟動語音辨識")
            } catch (e: Exception) {
                Log.e("CallMonitorService", "語音辨識啟動錯誤: ${e.message}")
            }
        }
    }

    private fun stopSpeechRecognition() {
        android.os.Handler(android.os.Looper.getMainLooper()).post {
            try {
                speechRecognizer?.stopListening()
                speechRecognizer?.destroy()
                speechRecognizer = null
                isRecognizerActive = false
                Log.d("CallMonitorService", "已停止並釋放語音辨識器")
            } catch (e: Exception) {
                Log.e("CallMonitorService", "停止語音辨識時出錯: ${e.message}")
            }
        }
    }

    // 使用 HTTP POST 將辨識到的對話文本與來電號碼傳送給 Flask 後端
    private fun sendTextToFlask(text: String, phoneNumber: String) {
        thread {
            try {
                val url = URL("${getBaseUrl()}/api/voice_dispatch")
                val conn = url.openConnection() as HttpURLConnection
                if (conn is HttpsURLConnection) {
                    conn.sslSocketFactory = getUnsafeSSLContext().socketFactory
                    conn.hostnameVerifier = trustAllVerifier
                }
                conn.requestMethod = "POST"
                conn.setRequestProperty("Content-Type", "application/json; utf-8")
                conn.doOutput = true
                conn.connectTimeout = 5000

                val jsonInput = JSONObject().apply {
                    put("text", text)
                    put("phone_number", phoneNumber)
                }

                OutputStreamWriter(conn.outputStream, "UTF-8").use { os ->
                    os.write(jsonInput.toString())
                    os.flush()
                }

                val responseCode = conn.responseCode
                Log.d("CallMonitorService", "傳送 Flask 成功，伺服器回應碼: $responseCode")
                conn.disconnect()
            } catch (e: Exception) {
                Log.e("CallMonitorService", "無法連線至 Flask 伺服器: ${e.message}")
            }
        }
    }

    // 啟動通話音訊錄製
    private fun startAudioRecording() {
        try {
            val dir = getExternalFilesDir(null) ?: filesDir
            val timeStamp = java.text.SimpleDateFormat("yyyyMMdd_HHmmss", java.util.Locale.getDefault()).format(java.util.Date())
            audioFile = java.io.File(dir, "Record_$timeStamp.m4a")
            
            mediaRecorder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                android.media.MediaRecorder(this)
            } else {
                @Suppress("DEPRECATION")
                android.media.MediaRecorder()
            }.apply {
                setAudioSource(android.media.MediaRecorder.AudioSource.MIC)
                setOutputFormat(android.media.MediaRecorder.OutputFormat.MPEG_4)
                setAudioEncoder(android.media.MediaRecorder.AudioEncoder.AAC)
                setOutputFile(audioFile?.absolutePath)
                prepare()
                start()
            }
            Log.d("CallMonitorService", "✅ 已啟動通話錄音，暫存路徑: ${audioFile?.absolutePath}")
        } catch (e: Exception) {
            Log.e("CallMonitorService", "啟動錄音失敗: ${e.message}")
        }
    }

    // 停止錄音並啟動上傳
    private fun stopAudioRecording() {
        try {
            mediaRecorder?.apply {
                stop()
                release()
            }
            mediaRecorder = null
            Log.d("CallMonitorService", "🛑 錄音已結束")
            
            val fileToUpload = audioFile
            if (fileToUpload != null && fileToUpload.exists()) {
                uploadRecordingFile(fileToUpload)
            }
        } catch (e: Exception) {
            Log.e("CallMonitorService", "停止錄音失敗: ${e.message}")
            try {
                mediaRecorder?.release()
            } catch (ex: Exception) {}
            mediaRecorder = null
        }
    }

    // 將錄音檔以 multipart/form-data 格式 POST 上傳至 Flask 伺服器
    private fun uploadRecordingFile(file: java.io.File) {
        thread {
            try {
                val boundary = "Boundary-${System.currentTimeMillis()}"
                val LINE_FEED = "\r\n"
                val url = URL("${getBaseUrl()}/api/upload_recording")
                val conn = url.openConnection() as HttpURLConnection
                if (conn is HttpsURLConnection) {
                    conn.sslSocketFactory = getUnsafeSSLContext().socketFactory
                    conn.hostnameVerifier = trustAllVerifier
                }
                conn.requestMethod = "POST"
                conn.doOutput = true
                conn.doInput = true
                conn.useCaches = false
                conn.setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
                conn.connectTimeout = 10000
                conn.readTimeout = 15000
                
                val outputStream = conn.outputStream
                val writer = java.io.PrintWriter(java.io.OutputStreamWriter(outputStream, "UTF-8"), true)
                
                writer.append("--$boundary").append(LINE_FEED)
                writer.append("Content-Disposition: form-data; name=\"file\"; filename=\"${file.name}\"").append(LINE_FEED)
                writer.append("Content-Type: audio/mp4").append(LINE_FEED)
                writer.append(LINE_FEED).flush()
                
                val fileInputStream = java.io.FileInputStream(file)
                val buffer = ByteArray(4096)
                var bytesRead = fileInputStream.read(buffer)
                while (bytesRead != -1) {
                    outputStream.write(buffer, 0, bytesRead)
                    bytesRead = fileInputStream.read(buffer)
                }
                outputStream.flush()
                fileInputStream.close()
                
                writer.append(LINE_FEED).flush()
                writer.append("--$boundary--").append(LINE_FEED).flush()
                writer.close()
                
                val responseCode = conn.responseCode
                if (responseCode == HttpURLConnection.HTTP_OK) {
                    Log.d("CallMonitorService", "✅ 錄音檔上傳 Flask 成功: ${file.name}")
                    if (file.delete()) {
                        Log.d("CallMonitorService", "🗑️ 手機本機暫存錄音檔已刪除")
                    }
                } else {
                    Log.e("CallMonitorService", "❌ 錄音檔上傳失敗，伺服器回應碼: $responseCode")
                }
                conn.disconnect()
            } catch (e: Exception) {
                Log.e("CallMonitorService", "無法連線至 Flask 上傳錄音檔: ${e.message}")
            }
        }
    }

    // 前景通知欄設定 (確保 Service 不被 Android 系統強制殺死)
    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val serviceChannel = NotificationChannel(
                CHANNEL_ID,
                "Portable 語音來電監控服務",
                NotificationManager.IMPORTANCE_LOW
            )
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(serviceChannel)
        }
    }

    private fun getServiceNotification(text: String): Notification {
        val notificationIntent = Intent(this, MainActivity::class.java)
        val pendingIntent = PendingIntent.getActivity(
            this, 0, notificationIntent,
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) PendingIntent.FLAG_IMMUTABLE else 0
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Portable 語音派遣背景服務中")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .build()
    }

    private fun updateNotification(text: String) {
        try {
            startForeground(NOTIFICATION_ID, getServiceNotification(text))
        } catch (e: Exception) {
            Log.e("CallMonitorService", "更新前景服務通知失敗: ${e.message}")
        }
    }

    override fun onBind(intent: Intent?): IBinder? {
        return null
    }

    override fun onDestroy() {
        super.onDestroy()
        stopSpeechRecognition()
        try {
            mSocket?.disconnect()
            mSocket?.off()
            mSocket = null
        } catch (e: Exception) {
            Log.e("CallMonitorService", "Error disconnecting socket: ${e.message}")
        }
    }
}
