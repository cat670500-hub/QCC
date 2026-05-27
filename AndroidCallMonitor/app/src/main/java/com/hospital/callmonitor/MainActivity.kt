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

class MainActivity : AppCompatActivity() {

    private lateinit var txtStatus: TextView
    private lateinit var editIpAddress: EditText
    private lateinit var btnToggle: Button
    
    private var isServiceRunning = false
    private val PERMISSION_REQUEST_CODE = 999

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        txtStatus = findViewById(R.id.txtStatus)
        editIpAddress = findViewById(R.id.editIpAddress)
        btnToggle = findViewById(R.id.btnToggle)

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
    }

    private fun startMonitorService() {
        val ip = editIpAddress.text.toString().trim()
        if (ip.isEmpty()) {
            Toast.makeText(this, "請輸入有效的 IP 位置", Toast.LENGTH_SHORT).show()
            return
        }

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
            Manifest.permission.MODIFY_AUDIO_SETTINGS
        )

        // Android 9 (Pie) 或以上需要額外授權 READ_CALL_LOG 才能在廣播中讀取來電號碼
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            permissions.add(Manifest.permission.READ_CALL_LOG)
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

    companion object {
        private const val PERMISSION_REQUEST_CODES = 999
    }
}
