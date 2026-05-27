package com.hospital.callmonitor

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.telephony.TelephonyManager
import android.util.Log

class CallBroadcastReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == TelephonyManager.ACTION_PHONE_STATE_CHANGED) {
            val state = intent.getStringExtra(TelephonyManager.EXTRA_STATE)
            val incomingNumber = intent.getStringExtra(TelephonyManager.EXTRA_INCOMING_NUMBER)
            
            Log.d("CallBroadcastReceiver", "來電狀態變更: $state, 號碼: $incomingNumber")

            val serviceIntent = Intent(context, CallMonitorService::class.java)

            when (state) {
                TelephonyManager.EXTRA_STATE_RINGING -> {
                    // 電話正在響鈴，啟動背景監控服務，準備接聽
                    serviceIntent.putExtra("call_state", "RINGING")
                    serviceIntent.putExtra("phone_number", incomingNumber ?: "未知")
                    context.startService(serviceIntent)
                }
                TelephonyManager.EXTRA_STATE_OFFHOOK -> {
                    // 接通電話，發送廣播讓服務開啟擴音，並啟動 Web Speech 錄音辨識
                    serviceIntent.putExtra("call_state", "OFFHOOK")
                    context.startService(serviceIntent)
                }
                TelephonyManager.EXTRA_STATE_IDLE -> {
                    // 掛斷電話，通知背景服務停止語音辨識並進行收尾
                    serviceIntent.putExtra("call_state", "IDLE")
                    context.startService(serviceIntent)
                }
            }
        }
    }
}
