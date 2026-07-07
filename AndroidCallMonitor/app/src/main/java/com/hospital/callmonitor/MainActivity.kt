package com.hospital.callmonitor

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import android.app.role.RoleManager

class MainActivity : AppCompatActivity() {

    private lateinit var txtStatus: TextView
    private lateinit var editIpAddress: EditText
    private lateinit var btnToggle: Button
    private lateinit var btnTestSpeech: Button
    private lateinit var txtLogHistory: TextView
    
    private var isServiceRunning = false
    private val PERMISSION_REQUEST_CODE = 999

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        txtStatus = findViewById(R.id.txtStatus)
        editIpAddress = findViewById(R.id.editIpAddress)
        btnToggle = findViewById(R.id.btnToggle)
        btnTestSpeech = findViewById(R.id.btnTestSpeech)
        txtLogHistory = findViewById(R.id.txtLogHistory)

        // 讀取先前儲存的 Flask IP
        val prefs = getSharedPreferences("CallMonitorPrefs", Context.MODE_PRIVATE)
        val savedIp = prefs.getString("flask_ip", "192.168.1.100")
        editIpAddress.setText(savedIp)

        // 檢查權限
        checkAndRequestPermissions()

        btnToggle.setOnClickListener {
            if (isServiceRunning) {
                stopMonitorService()
            } else {
                startMonitorService()
            }
        }
        
        btnTestSpeech.setOnClickListener {
            if (!isServiceRunning) {
                Toast.makeText(this, "請先啟用服務再進行測試！", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            Toast.makeText(this, "開始測試麥克風與辨識功能，請說話...", Toast.LENGTH_SHORT).show()
            val serviceIntent = Intent(this, CallMonitorService::class.java).apply {
                putExtra("action_test", true)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(serviceIntent)
            } else {
                startService(serviceIntent)
            }
        }
        
        // 註冊靜態回呼來更新日誌
        CallMonitorService.logListener = { msg ->
            runOnUiThread {
                val currentText = txtLogHistory.text.toString()
                // 最新的放在最上面
                txtLogHistory.text = msg + currentText
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        CallMonitorService.logListener = null
    }

    private fun startMonitorService() {
        val ip = editIpAddress.text.toString().trim()
        if (ip.isEmpty()) {
            Toast.makeText(this, "請輸入有效的 IP 位置", Toast.LENGTH_SHORT).show()
            return
        }

        // 檢查並提示用戶設定為預設撥號/通話程式 (Android 9.0+ 執行自動接聽所必需)
        checkDefaultDialer()

        // 儲存 IP 設定
        val prefs = getSharedPreferences("CallMonitorPrefs", Context.MODE_PRIVATE)
        prefs.edit().putString("flask_ip", ip).apply()

        // 啟動背景通話監控前景服務
        val serviceIntent = Intent(this, CallMonitorService::class.java).apply {
            putExtra("call_state", "IDLE") // 初始閒置狀態
        }
        
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(serviceIntent)
        } else {
            startService(serviceIntent)
        }

        isServiceRunning = true
        txtStatus.text = "🟢 來電監控與語音派遣運作中"
        txtStatus.setTextColor(Color.parseColor("#10b981")) // clinical success neon green
        btnToggle.text = "停止通話監控派遣"
        btnToggle.setBackgroundColor(Color.parseColor("#ef4444")) // danger red
        
        Toast.makeText(this, "來電語音自動派遣服務已開啟！", Toast.LENGTH_SHORT).show()
    }

    private fun stopMonitorService() {
        val serviceIntent = Intent(this, CallMonitorService::class.java)
        stopService(serviceIntent)

        isServiceRunning = false
        txtStatus.text = "🔴 已關閉 - 點選下方按鈕啟用"
        txtStatus.setTextColor(Color.parseColor("#ef4444"))
        btnToggle.text = "啟用來電自動語音派遣"
        btnToggle.setBackgroundColor(Color.parseColor("#0ea5e9")) // primary blue
        
        Toast.makeText(this, "語音派遣服務已停止", Toast.LENGTH_SHORT).show()
    }

    // 權限檢查與動態要求 (Android 6.0+)
    private fun checkAndRequestPermissions() {
        val permissions = mutableListOf(
            Manifest.permission.READ_PHONE_STATE,
            Manifest.permission.RECORD_AUDIO,
            Manifest.permission.MODIFY_AUDIO_SETTINGS,
            Manifest.permission.SEND_SMS
        )

        // Android 9 (Pie) 或以上需要額外授權 READ_CALL_LOG 才能在廣播中讀取來電號碼
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            permissions.add(Manifest.permission.READ_CALL_LOG)
        }

        // Android 8.0 (Oreo) 或以上需要額外授權 ANSWER_PHONE_CALLS 才能自動接聽來電
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            permissions.add(Manifest.permission.ANSWER_PHONE_CALLS)
        }

        // Android 13 (Tiramisu) 或以上需要動態要求 POST_NOTIFICATIONS
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            permissions.add(Manifest.permission.POST_NOTIFICATIONS)
        }

        val neededPermissions = permissions.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }

        if (neededPermissions.isNotEmpty()) {
            ActivityCompat.requestPermissions(
                this,
                neededPermissions.toTypedArray(),
                PERMISSION_REQUEST_CODE
            )
        }
        
        requestIgnoreBatteryOptimizations()
    }

    private fun requestIgnoreBatteryOptimizations() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            val intent = Intent()
            val packageName = packageName
            val pm = getSystemService(POWER_SERVICE) as android.os.PowerManager
            if (!pm.isIgnoringBatteryOptimizations(packageName)) {
                intent.action = android.provider.Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS
                intent.data = android.net.Uri.parse("package:$packageName")
                startActivity(intent)
            }
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == PERMISSION_REQUEST_CODES) {
            var allGranted = true
            for (result in grantResults) {
                if (result != PackageManager.PERMISSION_GRANTED) {
                    allGranted = false
                    break
                }
            }
            if (!allGranted) {
                Toast.makeText(this, "請授予所需權限以啟用完整自動監聽功能！", Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun checkDefaultDialer() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            try {
                val roleManager = getSystemService(RoleManager::class.java)
                if (roleManager != null && !roleManager.isRoleHeld(RoleManager.ROLE_DIALER)) {
                    val intent = roleManager.createRequestRoleIntent(RoleManager.ROLE_DIALER)
                    startActivityForResult(intent, PERMISSION_REQUEST_CODES)
                }
            } catch (e: Exception) {
                Toast.makeText(this, "設定預設撥號程式失敗(RoleManager): ${e.message}", Toast.LENGTH_LONG).show()
            }
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            try {
                val telecomManager = getSystemService(Context.TELECOM_SERVICE) as android.telecom.TelecomManager
                if (telecomManager.defaultDialerPackage != packageName) {
                    val intent = Intent(android.telecom.TelecomManager.ACTION_CHANGE_DEFAULT_DIALER).apply {
                        putExtra(android.telecom.TelecomManager.EXTRA_CHANGE_DEFAULT_DIALER_PACKAGE_NAME, packageName)
                    }
                    startActivity(intent)
                }
            } catch (e: Exception) {
                Toast.makeText(this, "設定預設撥號程式失敗(TelecomManager): ${e.message}", Toast.LENGTH_LONG).show()
            }
        }
    }

    companion object {
        private const val PERMISSION_REQUEST_CODES = 999
    }
}
