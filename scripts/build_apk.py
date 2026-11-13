"""Synthia Android APK Builder — পিসির Synthia নিয়ন্ত্রণের জন্য নেটিভ Android APK (SynthiaMobile.apk) তৈরি ও সাইন করে।"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.build_app import _png_bytes  # noqa: E402

DEFAULT_SDK_DIR = pathlib.Path(
    os.environ.get(
        "SYNTHIA_ANDROID_SDK",
        r"C:\Users\Abdullah Omar\.gemini\antigravity\brain\0b16dcc8-ce23-48bb-a453-5e197ee2b1db\scratch\android-sdk",
    )
)
APK_OUT = ROOT / "SynthiaMobile.apk"
BUILD_WORK = ROOT / "build" / "android_apk"


def _find_tool(sdk: pathlib.Path, name: str) -> pathlib.Path:
    hits = sorted(sdk.rglob(name))
    if not hits:
        raise FileNotFoundError(f"{name} not found under {sdk}")
    return hits[0]


def _detect_primary_lan_ip() -> str:
    try:
        from synthia.server import _get_lan_ips
        ips = _get_lan_ips()
        if ips:
            return ips[0]
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "192.168.0.107"


def _load_access_token() -> str:
    tf = ROOT / "synthia_data" / ".access_token"
    if tf.exists():
        return tf.read_text(encoding="utf-8").strip()
    try:
        from synthia.server import ACCESS_TOKEN
        return ACCESS_TOKEN
    except Exception:
        return ""


def _load_port() -> int:
    try:
        from synthia.config import settings
        return int(settings.get("server.port", 8765))
    except Exception:
        return 8765


MANIFEST_XML = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.synthia.commandbridge"
    android:versionCode="1"
    android:versionName="1.0.0">

    <uses-sdk android:minSdkVersion="24" android:targetSdkVersion="34" />

    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
    <uses-permission android:name="android.permission.ACCESS_WIFI_STATE" />
    <uses-permission android:name="android.permission.RECORD_AUDIO" />
    <uses-permission android:name="android.permission.MODIFY_AUDIO_SETTINGS" />
    <uses-permission android:name="android.permission.VIBRATE" />

    <application
        android:label="Synthia AI"
        android:icon="@mipmap/ic_launcher"
        android:usesCleartextTraffic="true"
        android:hardwareAccelerated="true"
        android:theme="@android:style/Theme.DeviceDefault.NoActionBar">
        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:windowSoftInputMode="adjustResize"
            android:configChanges="orientation|screenSize|keyboardHidden">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
"""

MAIN_ACTIVITY_JAVA = r"""package com.synthia.commandbridge;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.net.wifi.WifiInfo;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.Bundle;
import android.speech.RecognizerIntent;
import android.util.Base64;
import android.view.Window;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {
    private static final int REQ_RECORD_AUDIO = 101;
    private static final int REQ_SPEECH = 102;

    private WebView webView;
    private final ExecutorService executor = Executors.newCachedThreadPool();

    private volatile boolean isRecording = false;
    private volatile float lastAudioLevel = 0f;
    private AudioRecord audioRecord = null;
    private Thread recordThread = null;
    private ByteArrayOutputStream pcmStream = null;

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        Window w = getWindow();
        if (Build.VERSION.SDK_INT >= 21) {
            w.setStatusBarColor(Color.parseColor("#050a0f"));
            w.setNavigationBarColor(Color.parseColor("#050a0f"));
        }

        webView = new WebView(this);
        webView.setBackgroundColor(Color.parseColor("#050a0f"));
        WebSettings ws = webView.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setAllowFileAccess(true);
        ws.setMediaPlaybackRequiresUserGesture(false);
        if (Build.VERSION.SDK_INT >= 21) {
            ws.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        }

        webView.setWebViewClient(new WebViewClient());
        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(final PermissionRequest request) {
                runOnUiThread(() -> request.grant(request.getResources()));
            }
        });

        webView.addJavascriptInterface(new SynthiaBridge(), "SynthiaNative");
        setContentView(webView);
        webView.loadUrl("file:///android_asset/mobile/index.html");

        if (Build.VERSION.SDK_INT >= 23 && checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_RECORD_AUDIO);
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_SPEECH && resultCode == RESULT_OK && data != null) {
            ArrayList<String> matches = data.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS);
            if (matches != null && !matches.isEmpty()) {
                String text = matches.get(0);
                String js = "if(window.__onAndroidSpeechResult){window.__onAndroidSpeechResult(" + JSONObject.quote(text) + ");}";
                webView.post(() -> webView.evaluateJavascript(js, null));
            }
        }
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onDestroy() {
        stopWavInternal();
        executor.shutdownNow();
        super.onDestroy();
    }

    private byte[] stopWavInternal() {
        isRecording = false;
        lastAudioLevel = 0f;
        if (recordThread != null) {
            try { recordThread.join(1000); } catch (InterruptedException ignored) {}
            recordThread = null;
        }
        if (audioRecord != null) {
            try { audioRecord.stop(); } catch (Exception ignored) {}
            try { audioRecord.release(); } catch (Exception ignored) {}
            audioRecord = null;
        }
        if (pcmStream == null) return null;
        byte[] pcm = pcmStream.toByteArray();
        pcmStream = null;
        if (pcm.length < 320) return null;

        byte[] header = new byte[44];
        int totalDataLen = pcm.length + 36;
        int sampleRate = 16000;
        int channels = 1;
        int byteRate = sampleRate * channels * 2;
        header[0] = 'R'; header[1] = 'I'; header[2] = 'F'; header[3] = 'F';
        header[4] = (byte) (totalDataLen & 0xff);
        header[5] = (byte) ((totalDataLen >> 8) & 0xff);
        header[6] = (byte) ((totalDataLen >> 16) & 0xff);
        header[7] = (byte) ((totalDataLen >> 24) & 0xff);
        header[8] = 'W'; header[9] = 'A'; header[10] = 'V'; header[11] = 'E';
        header[12] = 'f'; header[13] = 'm'; header[14] = 't'; header[15] = ' ';
        header[16] = 16; header[17] = 0; header[18] = 0; header[19] = 0;
        header[20] = 1; header[21] = 0;
        header[22] = (byte) channels; header[23] = 0;
        header[24] = (byte) (sampleRate & 0xff);
        header[25] = (byte) ((sampleRate >> 8) & 0xff);
        header[26] = (byte) ((sampleRate >> 16) & 0xff);
        header[27] = (byte) ((sampleRate >> 24) & 0xff);
        header[28] = (byte) (byteRate & 0xff);
        header[29] = (byte) ((byteRate >> 8) & 0xff);
        header[30] = (byte) ((byteRate >> 16) & 0xff);
        header[31] = (byte) ((byteRate >> 24) & 0xff);
        header[32] = 2; header[33] = 0;
        header[34] = 16; header[35] = 0;
        header[36] = 'd'; header[37] = 'a'; header[38] = 't'; header[39] = 'a';
        header[40] = (byte) (pcm.length & 0xff);
        header[41] = (byte) ((pcm.length >> 8) & 0xff);
        header[42] = (byte) ((pcm.length >> 16) & 0xff);
        header[43] = (byte) ((pcm.length >> 24) & 0xff);

        byte[] wav = new byte[44 + pcm.length];
        System.arraycopy(header, 0, wav, 0, 44);
        System.arraycopy(pcm, 0, wav, 44, pcm.length);
        return wav;
    }

    public class SynthiaBridge {
        @JavascriptInterface
        public String getPhoneIp() {
            try {
                WifiManager wm = (WifiManager) getApplicationContext().getSystemService(WIFI_SERVICE);
                if (wm != null) {
                    WifiInfo wi = wm.getConnectionInfo();
                    int ip = wi.getIpAddress();
                    if (ip != 0) {
                        return (ip & 0xff) + "." + ((ip >> 8) & 0xff) + "." + ((ip >> 16) & 0xff) + "." + ((ip >> 24) & 0xff);
                    }
                }
            } catch (Exception ignored) {}
            return "";
        }

        @JavascriptInterface
        public void startAndroidSpeech(final String lang) {
            runOnUiThread(() -> {
                try {
                    Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
                    intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
                    intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, (lang != null && !lang.isEmpty()) ? lang : "bn-BD");
                    intent.putExtra(RecognizerIntent.EXTRA_PROMPT, "Synthia-কে বলুন...");
                    startActivityForResult(intent, REQ_SPEECH);
                } catch (Exception ignored) {}
            });
        }

        @JavascriptInterface
        public String startWavRecording() {
            if (Build.VERSION.SDK_INT >= 23 && checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                runOnUiThread(() -> requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_RECORD_AUDIO));
                return "PERMISSION_REQUIRED";
            }
            stopWavInternal();
            try {
                int sampleRate = 16000;
                int minBuf = AudioRecord.getMinBufferSize(sampleRate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
                int bufSize = Math.max(minBuf, 4096);
                audioRecord = new AudioRecord(MediaRecorder.AudioSource.MIC, sampleRate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, bufSize);
                if (audioRecord.getState() != AudioRecord.STATE_INITIALIZED) {
                    return "INIT_FAILED";
                }
                pcmStream = new ByteArrayOutputStream();
                isRecording = true;
                audioRecord.startRecording();
                recordThread = new Thread(() -> {
                    byte[] buf = new byte[bufSize];
                    while (isRecording && audioRecord != null) {
                        int read = audioRecord.read(buf, 0, buf.length);
                        if (read > 0 && pcmStream != null) {
                            pcmStream.write(buf, 0, read);
                            long sumSq = 0;
                            int samples = read / 2;
                            for (int i = 0; i < read - 1; i += 2) {
                                short s = (short) ((buf[i] & 0xFF) | (buf[i + 1] << 8));
                                sumSq += (long) s * s;
                            }
                            if (samples > 0) {
                                double rms = Math.sqrt((double) sumSq / samples) / 5500.0;
                                lastAudioLevel = (float) Math.min(1.0, Math.max(0.0, rms));
                            }
                        }
                    }
                });
                recordThread.start();
                return "OK";
            } catch (Exception e) {
                return "ERR:" + e.getMessage();
            }
        }

        @JavascriptInterface
        public float getAudioLevel() {
            return isRecording ? lastAudioLevel : 0f;
        }

        @JavascriptInterface
        public String stopWavRecording() {
            byte[] wav = stopWavInternal();
            if (wav == null) return "";
            return Base64.encodeToString(wav, Base64.NO_WRAP);
        }

        private volatile long preferCloudUntil = 0L;

        private byte[] mqttVarLen(int len) {
            ByteArrayOutputStream bo = new ByteArrayOutputStream();
            do {
                int b = len % 128;
                len /= 128;
                if (len > 0) b |= 0x80;
                bo.write(b);
            } while (len > 0);
            return bo.toByteArray();
        }

        private void mqttWriteStr(ByteArrayOutputStream bo, String s) throws Exception {
            byte[] b = s.getBytes(StandardCharsets.UTF_8);
            bo.write((b.length >> 8) & 0xFF);
            bo.write(b.length & 0xFF);
            bo.write(b);
        }

        private JSONObject cloudBridgeRequest(String bridgeId, String method, String pathAndQuery, String bodyJson) {
            String[] brokers = new String[]{"broker.emqx.io", "broker.hivemq.com"};
            String lastErr = "Cloud bridge unavailable";
            String reqId = UUID.randomUUID().toString().replace("-", "").substring(0, 16);
            String reqTopic = "synthia/v1/" + bridgeId + "/req";
            String resTopic = "synthia/v1/" + bridgeId + "/res/" + reqId;

            for (String broker : brokers) {
                Socket sock = null;
                try {
                    sock = new Socket();
                    sock.connect(new InetSocketAddress(broker, 1883), 4500);
                    boolean isHeavy = pathAndQuery.contains("/command") || pathAndQuery.contains("/voice");
                    sock.setSoTimeout(isHeavy ? 90000 : 12000);
                    OutputStream out = sock.getOutputStream();
                    DataInputStream in = new DataInputStream(sock.getInputStream());

                    // 1. CONNECT
                    ByteArrayOutputStream connVar = new ByteArrayOutputStream();
                    mqttWriteStr(connVar, "MQTT");
                    connVar.write(4);
                    connVar.write(2);
                    connVar.write(0);
                    connVar.write(30);
                    mqttWriteStr(connVar, "synthia_mob_" + reqId);
                    byte[] cBytes = connVar.toByteArray();
                    out.write(0x10);
                    out.write(mqttVarLen(cBytes.length));
                    out.write(cBytes);
                    out.flush();

                    int cType = (in.readUnsignedByte() >> 4);
                    int cLen = 0, cMul = 1;
                    while (true) {
                        int b = in.readUnsignedByte();
                        cLen += (b & 0x7F) * cMul;
                        if ((b & 0x80) == 0) break;
                        cMul *= 128;
                    }
                    if (cLen > 0) in.readFully(new byte[cLen]);
                    if (cType != 2) throw new Exception("MQTT CONNACK " + cType);

                    // 2. SUBSCRIBE to response topic
                    ByteArrayOutputStream subBody = new ByteArrayOutputStream();
                    subBody.write(0); subBody.write(1);
                    mqttWriteStr(subBody, resTopic);
                    subBody.write(0);
                    byte[] sBytes = subBody.toByteArray();
                    out.write(0x82);
                    out.write(mqttVarLen(sBytes.length));
                    out.write(sBytes);
                    out.flush();

                    // Read until SUBACK (type 9)
                    while (true) {
                        int pType = (in.readUnsignedByte() >> 4);
                        int pLen = 0, pMul = 1;
                        while (true) {
                            int b = in.readUnsignedByte();
                            pLen += (b & 0x7F) * pMul;
                            if ((b & 0x80) == 0) break;
                            pMul *= 128;
                        }
                        if (pLen > 0) in.readFully(new byte[pLen]);
                        if (pType == 9) break;
                    }

                    // 3. PUBLISH request
                    JSONObject reqObj = new JSONObject();
                    reqObj.put("req_id", reqId);
                    reqObj.put("method", method);
                    reqObj.put("path", pathAndQuery);
                    reqObj.put("body", bodyJson != null ? bodyJson : "");
                    byte[] msgBytes = reqObj.toString().getBytes(StandardCharsets.UTF_8);

                    ByteArrayOutputStream pubBody = new ByteArrayOutputStream();
                    mqttWriteStr(pubBody, reqTopic);
                    pubBody.write(msgBytes);
                    byte[] pBytes = pubBody.toByteArray();
                    out.write(0x30);
                    out.write(mqttVarLen(pBytes.length));
                    out.write(pBytes);
                    out.flush();

                    // 4. Wait for PUBLISH response
                    while (true) {
                        int hdr = in.readUnsignedByte();
                        int pType = (hdr >> 4);
                        int pLen = 0, pMul = 1;
                        while (true) {
                            int b = in.readUnsignedByte();
                            pLen += (b & 0x7F) * pMul;
                            if ((b & 0x80) == 0) break;
                            pMul *= 128;
                        }
                        byte[] payload = new byte[pLen];
                        if (pLen > 0) in.readFully(payload);
                        if (pType == 3 && pLen >= 2) {
                            int tLen = ((payload[0] & 0xFF) << 8) | (payload[1] & 0xFF);
                            int offset = 2 + tLen;
                            if ((hdr & 0x06) != 0) offset += 2;
                            if (offset <= pLen) {
                                String rxJson = new String(payload, offset, pLen - offset, StandardCharsets.UTF_8);
                                JSONObject rx = new JSONObject(rxJson);
                                rx.put("via", "cloud");
                                return rx;
                            }
                        }
                    }
                } catch (Exception e) {
                    lastErr = broker + ": " + (e.getMessage() != null ? e.getMessage() : "timeout");
                } finally {
                    if (sock != null) {
                        try { sock.close(); } catch (Exception ignored) {}
                    }
                }
            }
            JSONObject fail = new JSONObject();
            try {
                fail.put("ok", false);
                fail.put("status", 0);
                fail.put("via", "cloud");
                fail.put("error", "PC অফলাইন অথবা সাড়া দেয়নি (" + lastErr + ")");
            } catch (Exception ignored) {}
            return fail;
        }

        @JavascriptInterface
        public void httpRequest(final String urlStr, final String method, final String bodyJson, final String bridgeId, final String callbackName) {
            executor.execute(() -> {
                JSONObject res = new JSONObject();
                HttpURLConnection conn = null;
                boolean hasCloud = bridgeId != null && !bridgeId.trim().isEmpty();
                String phoneIp = getPhoneIp();
                boolean onWifi = phoneIp != null && !phoneIp.isEmpty() && !phoneIp.equals("0.0.0.0");
                boolean skipLan = hasCloud && (!onWifi || System.currentTimeMillis() < preferCloudUntil);
                boolean lanSucceeded = false;

                if (!skipLan) {
                    try {
                        boolean isPing = urlStr.contains("/api/mobile/ping");
                        URL url = new URL(urlStr);
                        conn = (HttpURLConnection) url.openConnection();
                        conn.setRequestMethod(method);
                        conn.setConnectTimeout(isPing ? 900 : 1200);
                        conn.setReadTimeout(isPing ? 1500 : 120000);
                        if (bodyJson != null && !bodyJson.isEmpty()) {
                            conn.setDoOutput(true);
                            conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                            byte[] out = bodyJson.getBytes(StandardCharsets.UTF_8);
                            try (OutputStream os = conn.getOutputStream()) {
                                os.write(out);
                            }
                        }
                        int code = conn.getResponseCode();
                        InputStream is = (code >= 200 && code < 400) ? conn.getInputStream() : conn.getErrorStream();
                        StringBuilder sb = new StringBuilder();
                        if (is != null) {
                            try (BufferedReader br = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8))) {
                                String line;
                                while ((line = br.readLine()) != null) sb.append(line);
                            }
                        }
                        res.put("ok", code >= 200 && code < 300);
                        res.put("status", code);
                        res.put("via", "lan");
                        res.put("body", sb.toString());
                        if (code < 200 || code >= 300) {
                            res.put("error", "HTTP " + code);
                        }
                        lanSucceeded = true;
                        preferCloudUntil = 0L;
                    } catch (Exception e) {
                        if (hasCloud) {
                            preferCloudUntil = System.currentTimeMillis() + 30000L;
                        } else {
                            try {
                                res.put("ok", false);
                                res.put("status", 0);
                                res.put("via", "lan");
                                res.put("error", e.getMessage() != null ? e.getMessage() : "Connection failed");
                            } catch (Exception ignored) {}
                        }
                    } finally {
                        if (conn != null) conn.disconnect();
                    }
                }

                if (!lanSucceeded && hasCloud) {
                    try {
                        URL u = new URL(urlStr);
                        String pq = u.getPath() + (u.getQuery() != null ? ("?" + u.getQuery()) : "");
                        res = cloudBridgeRequest(bridgeId.trim(), method, pq, bodyJson);
                    } catch (Exception e) {
                        try {
                            res.put("ok", false);
                            res.put("status", 0);
                            res.put("via", "cloud");
                            res.put("error", e.getMessage());
                        } catch (Exception ignored) {}
                    }
                }

                final String payload = res.toString();
                webView.post(() -> webView.evaluateJavascript(
                    "if(window[" + JSONObject.quote(callbackName) + "]){window[" + JSONObject.quote(callbackName) + "](" + JSONObject.quote(payload) + ");}",
                    null
                ));
            });
        }
    }
}
"""


def _run(cmd: list[str], cwd: pathlib.Path | None = None) -> None:
    r = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Command failed ({r.returncode}): {' '.join(cmd)}\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}")


def build_apk() -> pathlib.Path:
    sdk = DEFAULT_SDK_DIR
    javac = _find_tool(sdk, "javac.exe")
    keytool = _find_tool(sdk, "keytool.exe")
    java_exe = javac.parent / "java.exe"
    aapt2 = _find_tool(sdk, "aapt2.exe")
    zipalign = _find_tool(sdk, "zipalign.exe")
    d8_jar = _find_tool(sdk, "d8.jar")
    apksigner_jar = _find_tool(sdk, "apksigner.jar")
    android_jar = _find_tool(sdk, "android.jar")

    if BUILD_WORK.exists():
        shutil.rmtree(BUILD_WORK, ignore_errors=True)
    BUILD_WORK.mkdir(parents=True, exist_ok=True)

    res_dir = BUILD_WORK / "res"
    assets_dir = BUILD_WORK / "assets" / "mobile"
    src_dir = BUILD_WORK / "src" / "com" / "synthia" / "commandbridge"
    obj_dir = BUILD_WORK / "obj"
    dex_dir = BUILD_WORK / "dex"
    for d in (res_dir, assets_dir, src_dir, obj_dir, dex_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 1. Launcher Icons
    for folder, size in [
        ("mipmap-mdpi", 48),
        ("mipmap-hdpi", 72),
        ("mipmap-xhdpi", 96),
        ("mipmap-xxhdpi", 144),
        ("mipmap-xxxhdpi", 192),
    ]:
        mdir = res_dir / folder
        mdir.mkdir(parents=True, exist_ok=True)
        (mdir / "ic_launcher.png").write_bytes(_png_bytes(size))

    # 2. Bundle mobile.html with PC default LAN IP + Token + Cloud Bridge ID pre-baked
    mob_src = ROOT / "synthia" / "ui" / "mobile.html"
    mob_html = mob_src.read_text(encoding="utf-8")
    tok = _load_access_token()
    from synthia.cloud_bridge import get_bridge_id
    defaults = {
        "host": _detect_primary_lan_ip(),
        "port": _load_port(),
        "token": tok,
        "bridgeId": get_bridge_id(tok),
    }
    inject_script = f"<script>window.__SYNTHIA_DEFAULT_CONFIG__ = {json.dumps(defaults)};</script>\n</head>"
    mob_html = mob_html.replace("</head>", inject_script, 1)
    (assets_dir / "index.html").write_text(mob_html, encoding="utf-8")

    # 3. Manifest & Java Source
    manifest_path = BUILD_WORK / "AndroidManifest.xml"
    manifest_path.write_text(MANIFEST_XML, encoding="utf-8")
    java_file = src_dir / "MainActivity.java"
    java_file.write_text(MAIN_ACTIVITY_JAVA, encoding="utf-8")

    # 4. Compile Resources with aapt2
    res_zip = BUILD_WORK / "res.zip"
    _run([str(aapt2), "compile", "--dir", str(res_dir), "-o", str(res_zip)])

    unaligned_apk = BUILD_WORK / "app-unaligned.apk"
    _run([
        str(aapt2), "link",
        "-I", str(android_jar),
        "--manifest", str(manifest_path),
        "-A", str(BUILD_WORK / "assets"),
        "--java", str(BUILD_WORK / "gen"),
        "-o", str(unaligned_apk),
        str(res_zip),
    ])

    # 5. Compile Java -> .class -> classes.dex
    java_sources = [str(java_file)] + [str(p) for p in (BUILD_WORK / "gen").rglob("*.java")]
    _run([
        str(javac),
        "-source", "11", "-target", "11",
        "-encoding", "UTF-8",
        "-cp", str(android_jar),
        "-d", str(obj_dir),
        *java_sources,
    ])
    class_files = [str(p) for p in obj_dir.rglob("*.class")]
    _run([
        str(java_exe), "-cp", str(d8_jar), "com.android.tools.r8.D8",
        "--min-api", "24",
        "--lib", str(android_jar),
        "--output", str(dex_dir),
        *class_files,
    ])

    # 6. Inject classes.dex into APK
    import zipfile
    dex_apk = BUILD_WORK / "app-dex.apk"
    shutil.copy2(unaligned_apk, dex_apk)
    with zipfile.ZipFile(dex_apk, "a", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(dex_dir / "classes.dex", "classes.dex")

    # 7. Align & Sign APK
    aligned_apk = BUILD_WORK / "app-aligned.apk"
    _run([str(zipalign), "-f", "-p", "4", str(dex_apk), str(aligned_apk)])

    keystore = ROOT / "synthia_data" / "android-release.jks"
    keystore.parent.mkdir(parents=True, exist_ok=True)
    if not keystore.exists():
        _run([
            str(keytool), "-genkeypair", "-v",
            "-keystore", str(keystore),
            "-storepass", "synthia1234",
            "-keypass", "synthia1234",
            "-alias", "synthia",
            "-keyalg", "RSA",
            "-keysize", "2048",
            "-validity", "10000",
            "-dname", "CN=Synthia AI, OU=Mobile, O=Synthia, L=Dhaka, S=Dhaka, C=BD",
        ])

    _run([
        str(java_exe), "-jar", str(apksigner_jar), "sign",
        "--ks", str(keystore),
        "--ks-pass", "pass:synthia1234",
        "--key-pass", "pass:synthia1234",
        "--ks-key-alias", "synthia",
        "--out", str(APK_OUT),
        str(aligned_apk),
    ])

    print(f"[apk] Built & signed: {APK_OUT} ({APK_OUT.stat().st_size:,} bytes)")
    print(f"[apk] Baked PC host: {defaults['host']}:{defaults['port']} (token len={len(defaults['token'])})")
    return APK_OUT


if __name__ == "__main__":
    build_apk()
