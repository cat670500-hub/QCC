package com.hospital.callmonitor

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.telephony.TelephonyManager
import android.util.Log
import android.os.Build

class CallBroadcastReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == TelephonyManager.ACTION_PHONE_STATE_CHANGED) {
            val state = intent.getStringExtra(TelephonyManager.EXTRA_STATE)
            val incomingNumber = intent.getStringExtra(TelephonyManager.EXTRA_INCOMING_NUMBER)
            
            Log.d("CallBroadcastReceiver", "來電狀態變更: $state, 號碼: $incomingNumber")

            val serviceIntent = Intent(context, CallMonitorService::class.java).apply {
                when (state) {
                    TelephonyManager.EXTRA_STATE_RINGING -> {
                        putExtra("call_state", "RINGING")
                        putExtra("phone_number", incomingNumber ?: "未知")
                    }
                    TelephonyManager.EXTRA_STATE_OFFHOOK -> {
                        putExtra("call_state", "OFFHOOK")
                    }
                    TelephonyManager.EXTRA_STATE_IDLE -> {
                        putExtra("call_state", "IDLE")
                    }
                }
            }

            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    context.startForegroundService(serviceIntent)
                } else {
                    context.startService(serviceIntent)
                }
                Log.d("CallBroadcastReceiver", "已送出啟動背景服務命令以處理狀態: $state")
            } catch (e: Exception) {
                Log.e("CallBroadcastReceiver", "啟動通話監控背景服務時發生異常: ${e.message}")
            }
        }
    }
}
