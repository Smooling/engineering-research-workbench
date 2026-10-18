package com.smooling.researchworkbench;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.util.Base64;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.webkit.JavascriptInterface;
import android.webkit.JsResult;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceError;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/** Local-first Android host. Only the phone-local origin is rendered in this WebView. */
public class MainActivity extends Activity {
    private static final int PICK_FILES = 101;
    private static final int SAVE_FILE = 102;
    private static final ExecutorService WORKER = Executors.newSingleThreadExecutor();
    private static String backendUrl;
    private WebView webView;
    private FrameLayout root;
    private LinearLayout loading;
    private TextView status;
    private ValueCallback<Uri[]> fileCallback;
    private File pendingDownload;
    private boolean backPending;

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        root = new FrameLayout(this);
        root.setBackgroundColor(Color.rgb(247, 248, 251));
        setContentView(root);
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets bars = insets.getInsets(
                    WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                int keyboard = insets.getInsets(WindowInsets.Type.ime()).bottom;
                view.setPadding(bars.left, bars.top, bars.right, Math.max(bars.bottom, keyboard));
                if (webView != null) webView.evaluateJavascript(
                    "window.ERWAndroid && window.ERWAndroid.setKeyboardVisible(" +
                    insets.isVisible(WindowInsets.Type.ime()) + ");", null);
                return WindowInsets.CONSUMED;
            }
            view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets.consumeSystemWindowInsets();
        });
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        createWebView();
        showLoading("正在启动本地工作台…");
        WORKER.execute(() -> {
            try {
                if (backendUrl == null) {
                    File assets = new File(getCacheDir(), "workbench-assets");
                    unpackAssets(assets);
                    if (!Python.isStarted()) Python.start(new AndroidPlatform(getApplicationContext()));
                    backendUrl = Python.getInstance().getModule("android_runtime").callAttr("start",
                        new File(getFilesDir(), "workbench").getAbsolutePath(),
                        assets.getAbsolutePath()).toString();
                }
                runOnUiThread(() -> { if (!isDestroyed()) webView.loadUrl(backendUrl); });
            } catch (Exception error) {
                android.util.Log.e("Workbench", "Backend startup failed", error);
                runOnUiThread(() -> { if (!isDestroyed()) status.setText("启动失败\n" + error.getMessage()); });
            }
        });
    }

    private void showLoading(String message) {
        if (loading == null) {
            loading = new LinearLayout(this);
            loading.setOrientation(LinearLayout.VERTICAL);
            loading.setGravity(Gravity.CENTER);
            loading.setPadding(32, 32, 32, 32);
            loading.setBackgroundColor(Color.rgb(247, 248, 251));
            TextView title = new TextView(this);
            title.setText("科研工作台");
            title.setTextSize(24);
            title.setTextColor(Color.rgb(35, 42, 64));
            loading.addView(title);
            loading.addView(new ProgressBar(this));
            status = new TextView(this);
            status.setGravity(Gravity.CENTER);
            status.setPadding(0, 24, 0, 0);
            status.setTextColor(Color.rgb(85, 91, 108));
            loading.addView(status);
            root.addView(loading, new FrameLayout.LayoutParams(-1, -1));
        }
        status.setText(message);
        loading.setVisibility(View.VISIBLE);
    }

    private void unpackAssets(File directory) throws Exception {
        if (!directory.isDirectory() && !directory.mkdirs()) throw new Exception("无法创建资源目录");
        String prefix = directory.getCanonicalPath() + File.separator;
        try (ZipInputStream zip = new ZipInputStream(getAssets().open("workbench.zip"))) {
            ZipEntry entry;
            byte[] buffer = new byte[32768];
            while ((entry = zip.getNextEntry()) != null) {
                File target = new File(directory, entry.getName());
                if (!target.getCanonicalPath().startsWith(prefix)) throw new Exception("资源路径无效");
                if (entry.isDirectory()) { target.mkdirs(); continue; }
                File parent = target.getParentFile();
                if (!parent.isDirectory() && !parent.mkdirs()) throw new Exception("无法解压资源");
                try (OutputStream out = new FileOutputStream(target)) {
                    int n;
                    while ((n = zip.read(buffer)) != -1) out.write(buffer, 0, n);
                }
            }
        }
    }

    @android.annotation.SuppressLint("SetJavaScriptEnabled")
    private void createWebView() {
        webView = new WebView(this);
        webView.setBackgroundColor(Color.rgb(247, 248, 251));
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSupportMultipleWindows(false);
        settings.setUserAgentString(settings.getUserAgentString() + " ResearchWorkbenchAndroid/1");
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);
        webView.addJavascriptInterface(new HostBridge(), "AndroidHost");
        webView.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                String url = request.getUrl().toString();
                if (isLocal(url)) return false;
                if (request.isForMainFrame()) openExternal(request.getUrl());
                return true;
            }
            @Override public void onPageFinished(WebView view, String url) {
                if (isLocal(url)) loading.setVisibility(View.GONE);
            }
            @Override public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) showLoading("页面加载失败，请关闭并重新打开应用。\n" + error.getDescription());
            }
        });
        webView.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback,
                                                       FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = callback;
                Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                intent.setType("*/*");
                String[] accept = params.getAcceptTypes();
                if (accept.length > 0 && !accept[0].isEmpty()) intent.putExtra(Intent.EXTRA_MIME_TYPES, accept);
                intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE);
                try { startActivityForResult(intent, PICK_FILES); }
                catch (Exception error) { fileCallback.onReceiveValue(null); fileCallback = null; toast("没有可用的文件选择器"); }
                return true;
            }
            @Override public boolean onJsAlert(WebView view, String url, String message, JsResult result) {
                new AlertDialog.Builder(MainActivity.this).setMessage(message)
                    .setPositiveButton("确定", (dialog, which) -> result.confirm())
                    .setOnCancelListener(dialog -> result.cancel()).show();
                return true;
            }
            @Override public boolean onJsConfirm(WebView view, String url, String message, JsResult result) {
                new AlertDialog.Builder(MainActivity.this).setMessage(message)
                    .setPositiveButton("确定", (dialog, which) -> result.confirm())
                    .setNegativeButton("取消", (dialog, which) -> result.cancel())
                    .setOnCancelListener(dialog -> result.cancel()).show();
                return true;
            }
        });
        webView.setDownloadListener((url, agent, disposition, mime, length) -> {
            if (isLocal(url)) downloadLocal(url, mime);
            else if (url.startsWith("blob:")) {
                String script = "fetch(" + JSONObject.quote(url) + ").then(r=>r.blob()).then(b=>{"
                    + "if(b.size>33554432)throw Error('文件超过 32 MB，请使用电脑导出');"
                    + "const r=new FileReader();r.onload=()=>AndroidHost.saveBase64('download',b.type,r.result.split(',')[1]);"
                    + "r.readAsDataURL(b)}).catch(e=>alert(e.message))";
                webView.evaluateJavascript(script, null);
            } else openExternal(Uri.parse(url));
        });
        root.addView(webView, new FrameLayout.LayoutParams(-1, -1));
    }

    private boolean isLocal(String url) {
        if (backendUrl == null) return false;
        Uri uri = Uri.parse(url), origin = Uri.parse(backendUrl);
        return "http".equals(uri.getScheme()) && origin.getHost().equals(uri.getHost())
            && origin.getPort() == uri.getPort();
    }

    private void openExternal(Uri uri) {
        String scheme = uri.getScheme();
        if (!"https".equals(scheme) && !"http".equals(scheme) && !"mailto".equals(scheme)) return;
        try { startActivity(new Intent(Intent.ACTION_VIEW, uri)); }
        catch (Exception error) { toast("没有可用的应用打开此链接"); }
    }

    private void downloadLocal(String url, String mime) {
        WORKER.execute(() -> {
            HttpURLConnection connection = null;
            try {
                connection = (HttpURLConnection) new URL(url).openConnection();
                connection.setInstanceFollowRedirects(false);
                connection.setConnectTimeout(10000);
                connection.setReadTimeout(30000);
                if (connection.getResponseCode() != 200) throw new Exception("下载失败");
                File target = File.createTempFile("download-", ".tmp", getCacheDir());
                try (InputStream in = connection.getInputStream(); OutputStream out = new FileOutputStream(target)) {
                    copy(in, out);
                }
                runOnUiThread(() -> saveFile(target, "download", mime));
            } catch (Exception error) { toast(error.getMessage()); }
            finally { if (connection != null) connection.disconnect(); }
        });
    }

    private void saveFile(File file, String name, String mime) {
        if (isDestroyed()) { file.delete(); return; }
        if (pendingDownload != null) { file.delete(); toast("请先完成当前文件保存"); return; }
        pendingDownload = file;
        Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType(mime == null || mime.isEmpty() ? "application/octet-stream" : mime);
        intent.putExtra(Intent.EXTRA_TITLE, name);
        try { startActivityForResult(intent, SAVE_FILE); }
        catch (Exception error) { pendingDownload.delete(); pendingDownload = null; toast("无法打开保存位置"); }
    }

    private class HostBridge {
        @JavascriptInterface public void copyText(String text) {
            runOnUiThread(() -> ((ClipboardManager) getSystemService(CLIPBOARD_SERVICE))
                .setPrimaryClip(ClipData.newPlainText("科研工作台", text)));
        }
        @JavascriptInterface public void requestBackup() {
            WORKER.execute(() -> {
                try {
                    File target = File.createTempFile("workbench-backup-", ".zip", getCacheDir());
                    Python.getInstance().getModule("android_runtime").callAttr("export_backup", target.getAbsolutePath());
                    String date = new SimpleDateFormat("yyyyMMdd-HHmm", Locale.ROOT).format(new Date());
                    runOnUiThread(() -> saveFile(target, "ResearchWorkbench-" + date + ".zip", "application/zip"));
                } catch (Exception error) { toast("备份失败：" + error.getMessage()); }
            });
        }
        @JavascriptInterface public void saveBase64(String name, String mime, String data) {
            if (data.length() > 45000000) { toast("文件过大，请使用电脑导出"); return; }
            WORKER.execute(() -> {
                try {
                    File target = File.createTempFile("download-", ".tmp", getCacheDir());
                    try (OutputStream out = new FileOutputStream(target)) { out.write(Base64.decode(data, Base64.DEFAULT)); }
                    String safeName = new File(name).getName().replaceAll("[\\p{Cntrl}]", "");
                    runOnUiThread(() -> saveFile(target, safeName, mime));
                } catch (Exception error) { toast("导出失败：" + error.getMessage()); }
            });
        }
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == PICK_FILES && fileCallback != null) {
            Uri[] uris = null;
            if (result == RESULT_OK && data != null) {
                ClipData clips = data.getClipData();
                if (clips != null) {
                    uris = new Uri[clips.getItemCount()];
                    for (int i = 0; i < uris.length; i++) uris[i] = clips.getItemAt(i).getUri();
                } else if (data.getData() != null) uris = new Uri[] {data.getData()};
            }
            fileCallback.onReceiveValue(uris);
            fileCallback = null;
        } else if (request == SAVE_FILE && pendingDownload != null) {
            File source = pendingDownload;
            pendingDownload = null;
            Uri uri = data == null ? null : data.getData();
            if (result != RESULT_OK || uri == null) { source.delete(); return; }
            WORKER.execute(() -> {
                try (InputStream in = new java.io.FileInputStream(source);
                     OutputStream out = getContentResolver().openOutputStream(uri)) {
                    if (out == null) throw new Exception("无法写入保存位置");
                    copy(in, out);
                    toast("文件已保存");
                } catch (Exception error) { toast("保存失败：" + error.getMessage()); }
                finally { source.delete(); }
            });
        }
    }

    private static void copy(InputStream in, OutputStream out) throws Exception {
        byte[] buffer = new byte[32768];
        int count;
        while ((count = in.read(buffer)) != -1) out.write(buffer, 0, count);
    }
    private void toast(String text) { runOnUiThread(() -> Toast.makeText(this, text, Toast.LENGTH_LONG).show()); }

    @Override public void onBackPressed() {
        if (backPending) return;
        if (loading.getVisibility() == View.VISIBLE) { moveTaskToBack(true); return; }
        backPending = true;
        webView.evaluateJavascript("Boolean(window.ERWAndroid && window.ERWAndroid.handleBack())", value -> {
            backPending = false;
            if (!"true".equals(value)) moveTaskToBack(true);
        });
    }

    @Override protected void onDestroy() {
        if (fileCallback != null) fileCallback.onReceiveValue(null);
        if (pendingDownload != null) pendingDownload.delete();
        webView.removeJavascriptInterface("AndroidHost");
        webView.destroy();
        super.onDestroy();
    }
}
