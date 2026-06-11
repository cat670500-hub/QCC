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
import io.socket.client.IO
import io.socket.client.Socket

class CallMonitorService : Service() {

    private lateinit var audioManager: AudioManager
    private var speechRecognizer: SpeechRecognizer? = null
    private var isRecognizerActive = false
    private var flaskIpAddress = "192.168.1.100" // 預設 IP，可在 App 畫面修改
    private var mSocket: Socket? = null
    private val NOTIFICATION_ID = 888
    private val CHANNEL_ID = "CallMonitorChannel"

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
    }

    private fun initSocket() {
        try {
            val opts = IO.Options().apply {
                forceNew = true
                reconnection = true
            }
            mSocket = IO.socket("http://$flaskIpAddress:5000", opts)
            
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
        val callState = intent?.getStringExtra("call_state")
        val phoneNumber = intent?.getStringExtra("phone_number") ?: "未知"

        Log.d("CallMonitorService", "服務收到命令狀態: $callState")

        when (callState) {
            "RINGING" -> {
                updateNotification("來電響鈴中: $phoneNumber")
                // 自動接聽來電
                try {
                    val telecomManager = getSystemService(Context.TELECOM_SERVICE) as TelecomManager
                    if (androidx.core.content.ContextCompat.checkSelfPermission(this, android.Manifest.permission.ANSWER_PHONE_CALLS) == PackageManager.PERMISSION_GRANTED) {
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
            "OFFHOOK" -> {
                updateNotification("通話中 - 語音派遣自動監聽已開啟")
                // 1. 自動開啟擴音
                enableSpeakerphone(true)
                // 2. 啟動 Google 語音辨識
                startSpeechRecognition()
            }
            "IDLE" -> {
                updateNotification("通話結束 - 語音監聽暫停")
                // 1. 關閉擴音
                enableSpeakerphone(false)
                // 2. 停止語音辨識
                stopSpeechRecognition()
            }
        }

        return START_STICKY
    }

    // 控制擴音 (Speakerphone)
    private fun enableSpeakerphone(enable: Boolean) {
        try {
            thread {
                Thread.sleep(1000) // 延遲 1 秒等通話管道穩定
                if (enable) {
                    audioManager.mode = AudioManager.MODE_IN_CALL
                    audioManager.isSpeakerphoneOn = true
                    Log.d("CallMonitorService", "✅ 已自動切換至「免持擴音」模式！")
                } else {
                    audioManager.isSpeakerphoneOn = false
                    audioManager.mode = AudioManager.MODE_NORMAL
                    Log.d("CallMonitorService", "🛑 已回復正常聽筒模式")
                }
            }
        } catch (e: Exception) {
            Log.e("CallMonitorService", "切換擴音失敗: ${e.message}")
        }
    }

    // 啟動語音辨識
    private fun startSpeechRecognition() {
        if (isRecognizerActive) return

        thread(start = true) {
            // Android 規定語音辨識必須在 UI 主線程上建立與執行
            mainLooper.queue.addIdleHandler {
                speechRecognizer = SpeechRecognizer.createSpeechRecognizer(this@CallMonitorService)
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
                    }
                    override fun onBeginningOfSpeech() {}
                    override fun onRmsChanged(rmsdB: Float) {}
                    override fun onBufferReceived(buffer: ByteArray?) {}
                    override fun onEndOfSpeech() {}
                    
                    override fun onError(error: Int) {
                        Log.e("SpeechRecognizer", "辨識錯誤碼: $error")
                        isRecognizerActive = false
                        // 如果仍在通話中，超時或中斷則自動重新啟動辨識
                        if (audioManager.isSpeakerphoneOn) {
                            startSpeechRecognition()
                        }
                    }

                    override fun onResults(results: Bundle?) {
                        isRecognizerActive = false
                        val matches = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                        if (!matches.isNullOrEmpty()) {
                            val recognizedText = matches[0]
                            Log.d("SpeechRecognizer", "🎙️ 通話辨識文本: $recognizedText")
                            
                            // 將辨識結果 POST 給 Flask 伺服器
                            sendTextToFlask(recognizedText)
                        }

                        // 如果電話仍在通話中（擴音開啟中），就重啟辨識，實現連續監聽
                        if (audioManager.isSpeakerphoneOn) {
                            startSpeechRecognition()
                        }
                    }

                    override fun onPartialResults(partialResults: Bundle?) {}
                    override fun onEvent(eventType: Int, params: Bundle?) {}
                })

                speechRecognizer?.startListening(intent)
                true
            }
        }
    }

    private fun stopSpeechRecognition() {
        mainLooper.queue.addIdleHandler {
            speechRecognizer?.stopListening()
            speechRecognizer?.destroy()
            speechRecognizer = null
            isRecognizerActive = false
            true
        }
    }

    // 使用 HTTP POST 將辨識到的對話文本傳送給 Flask 後端
    private fun sendTextToFlask(text: String) {
        thread {
            try {
                val url = URL("http://$flaskIpAddress:5000/api/voice_dispatch")
                val conn = url.openConnection() as HttpURLConnection
                conn.requestMethod = "POST"
                conn.setRequestProperty("Content-Type", "application/json; utf-8")
                conn.doOutput = true
                conn.connectTimeout = 5000

                val jsonInput = JSONObject().apply {
                    put("text", text)
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
        val notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        notificationManager.notify(NOTIFICATION_ID, getServiceNotification(text))
    }

    override fun onBind(intent: Intent?): IBinder? {
        return null
    }

    override fun onDestroy() {
        super.onDestroy()
        stopSpeechRecognition()
        enableSpeakerphone(false)
        try {
            mSocket?.disconnect()
            mSocket?.off()
            mSocket = null
        } catch (e: Exception) {
            Log.e("CallMonitorService", "Error disconnecting socket: ${e.message}")
        }
    }
}
