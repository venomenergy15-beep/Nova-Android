package com.nova.assistant

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.speech.RecognizerIntent
import android.speech.tts.TextToSpeech
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale
import java.util.concurrent.TimeUnit

private val Night = Color(0xFF070B16)
private val Panel = Color(0xFF111A2B)
private val Cyan = Color(0xFF54E6FF)
private val Violet = Color(0xFF9B7CFF)

data class ChatLine(val text: String, val fromUser: Boolean)

class MainActivity : ComponentActivity(), TextToSpeech.OnInitListener {
    private var tts: TextToSpeech? = null
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        tts = TextToSpeech(this, this)
        setContent { NovaApp(onSpeak = { speak(it) }) }
    }
    override fun onInit(status: Int) {
        if (status == TextToSpeech.SUCCESS) tts?.language = Locale.getDefault()
    }
    private fun speak(text: String) { tts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "nova_reply") }
    override fun onDestroy() { tts?.shutdown(); super.onDestroy() }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NovaApp(onSpeak: (String) -> Unit) {
    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences("nova_settings", 0) }
    var endpoint by remember { mutableStateOf(prefs.getString("endpoint", "") ?: "") }
    var apiKey by remember { mutableStateOf(prefs.getString("key", "") ?: "") }
    var model by remember { mutableStateOf(prefs.getString("model", "gpt-4o-mini") ?: "gpt-4o-mini") }
    var offlineMode by remember { mutableStateOf(false) }
    var showSettings by remember { mutableStateOf(false) }
    var input by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf("Ready • Local interface") }
    var speakReplies by remember { mutableStateOf(prefs.getBoolean("speak_replies", true)) }
    val memories = remember { mutableStateListOf<String>().apply { addAll(prefs.getStringSet("memories", emptySet()) ?: emptySet()) } }
    val scope = rememberCoroutineScope()
    val messages = remember {
        mutableStateListOf(
            ChatLine("Hello. I'm NOVA, your personal AI assistant.", false),
            ChatLine("My interface and voice features are ready. Connect an AI provider in Settings to enable online answers.", false)
        )
    }

    val speechLauncher = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val spoken = result.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()
        if (!spoken.isNullOrBlank()) input = spoken
    }
    val permissionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) {
            val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_PROMPT, "Talk to NOVA")
            }
            runCatching { speechLauncher.launch(intent) }
                .onFailure { status = "Speech recognition is unavailable on this device." }
        } else status = "Microphone permission was not granted."
    }

    fun sendMessage() {
        val prompt = input.trim()
        if (prompt.isEmpty() || busy) return
        messages.add(ChatLine(prompt, true))
        input = ""

        // Explicit user-directed memory: "remember: ..." saves only what the user asks NOVA to retain.
        if (prompt.startsWith("remember:", ignoreCase = true)) {
            val fact = prompt.substringAfter(":").trim()
            if (fact.isNotBlank()) {
                memories.add(fact)
                prefs.edit().putStringSet("memories", memories.toSet()).apply()
                val reply = "Saved to NOVA's private on-device memory. You can review or erase it in Settings."
                messages.add(ChatLine(reply, false))
                if (speakReplies) onSpeak(reply)
                status = "Memory updated locally"
            }
            return
        }
        if (prompt.equals("forget all memories", ignoreCase = true)) {
            memories.clear()
            prefs.edit().remove("memories").apply()
            val reply = "All saved NOVA memories have been cleared from this app."
            messages.add(ChatLine(reply, false))
            if (speakReplies) onSpeak(reply)
            status = "Local memory cleared"
            return
        }
        if (offlineMode) {
            val reply = "Offline mode is selected, but a local language model is not installed yet. Saved memories remain available on this device; offline reasoning is the next integration milestone."
            messages.add(ChatLine(reply, false))
            if (speakReplies) onSpeak(reply)
            status = "Offline • local model not connected"
            return
        }
        if (endpoint.isBlank() || model.isBlank()) {
            messages.add(ChatLine("Please configure an OpenAI-compatible API endpoint and model in Settings. Until then, NOVA can store local notes but cannot generate cloud AI responses.", false))
            status = "Online provider not configured"
            return
        }
        busy = true
        status = "Connecting to your AI provider…"
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    val client = OkHttpClient.Builder()
                        .callTimeout(60, TimeUnit.SECONDS)
                        .build()
                    val conversation = JSONArray()
                    val memoryText = memories.joinToString("\\n") { "- $it" }
                    val systemText = buildString {
                        append("You are NOVA, the user's personal assistant. Be helpful, honest, capable, and clear about limitations. ")
                        append("Use the following user-approved memories only when relevant. Do not claim to learn or remember anything unless it is saved by the app. ")
                        if (memoryText.isNotBlank()) append("\\nUser-approved memory:\\n$memoryText")
                    }
                    conversation.put(JSONObject().put("role", "system").put("content", systemText))
                    messages.takeLast(12).forEach { line ->
                        conversation.put(JSONObject()
                            .put("role", if (line.fromUser) "user" else "assistant")
                            .put("content", line.text))
                    }
                    val body = JSONObject().apply {
                        put("model", model)
                        put("messages", conversation)
                    }.toString()
                    val requestBuilder = Request.Builder()
                        .url(endpoint.trimEnd('/') + "/chat/completions")
                        .post(body.toRequestBody("application/json".toMediaType()))
                        .header("Content-Type", "application/json")
                    if (apiKey.isNotBlank()) requestBuilder.header("Authorization", "Bearer $apiKey")
                    client.newCall(requestBuilder.build()).execute().use { response ->
                        val raw = response.body?.string().orEmpty()
                        if (!response.isSuccessful) error("Provider returned HTTP ${response.code}: ${raw.take(300)}")
                        val json = JSONObject(raw)
                        json.getJSONArray("choices").getJSONObject(0)
                            .getJSONObject("message").getString("content")
                    }
                }.getOrElse { "Connection error: ${it.message ?: "Unknown error"}" }
            }
            messages.add(ChatLine(result, false))
            status = if (result.startsWith("Connection error:")) "Provider connection failed" else "Online • response received"
            if (speakReplies && !result.startsWith("Connection error:")) onSpeak(result)
            busy = false
        }
    }

    MaterialTheme(colorScheme = darkColorScheme(
        primary = Cyan, secondary = Violet, background = Night, surface = Panel,
        onBackground = Color.White, onSurface = Color.White
    )) {
        Scaffold(containerColor = Night, topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("N O V A", color = Cyan, fontWeight = FontWeight.Bold, letterSpacing = 4.sp)
                        Text("PERSONAL INTELLIGENCE", color = Color(0xFF8A9AB8), fontSize = 9.sp, letterSpacing = 2.sp)
                    }
                },
                actions = {
                    IconButton(onClick = { showSettings = true }) {
                        Icon(Icons.Default.Settings, "Settings", tint = Cyan)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Night)
            )
        }) { padding ->
            Column(Modifier.fillMaxSize().padding(padding).padding(horizontal = 14.dp)) {
                Box(
                    Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 12.dp)
                        .background(Brush.linearGradient(listOf(Color(0xFF132B45), Color(0xFF211A40))), RoundedCornerShape(22.dp))
                        .padding(18.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Box(
                            Modifier.size(94.dp).background(
                                Brush.radialGradient(listOf(Color(0xFF315E8D), Color(0xFF17213D), Night)),
                                CircleShape
                            ),
                            contentAlignment = Alignment.Center
                        ) {
                            Text("N", color = Cyan, fontSize = 42.sp, fontWeight = FontWeight.Light)
                        }
                        Spacer(Modifier.height(8.dp))
                        Text(if (offlineMode) "LOCAL MODE" else "NOVA CORE", color = Cyan, letterSpacing = 3.sp, fontSize = 12.sp)
                        Text(status, color = Color(0xFF9EACC4), fontSize = 11.sp)
                    }
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                    Text("CONVERSATION", color = Color(0xFF9EACC4), fontSize = 11.sp, letterSpacing = 2.sp)
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("OFFLINE", color = if (offlineMode) Cyan else Color.Gray, fontSize = 10.sp)
                        Switch(checked = offlineMode, onCheckedChange = { offlineMode = it })
                    }
                }
                LazyColumn(Modifier.weight(1f).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.dp), contentPadding = PaddingValues(vertical = 10.dp)) {
                    items(messages) { line ->
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = if (line.fromUser) Arrangement.End else Arrangement.Start) {
                            Surface(
                                color = if (line.fromUser) Color(0xFF173C55) else Panel,
                                shape = RoundedCornerShape(16.dp),
                                modifier = Modifier.fillMaxWidth(0.88f)
                            ) {
                                Text(line.text, Modifier.padding(13.dp), color = Color.White, fontSize = 14.sp)
                            }
                        }
                    }
                }
                Row(
                    Modifier.fillMaxWidth().padding(bottom = 12.dp)
                        .background(Panel, RoundedCornerShape(24.dp)).padding(horizontal = 8.dp, vertical = 5.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    IconButton(onClick = {
                        if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                            val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                                putExtra(RecognizerIntent.EXTRA_PROMPT, "Talk to NOVA")
                            }
                            runCatching { speechLauncher.launch(intent) }.onFailure { status = "Speech recognition unavailable." }
                        } else permissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                    }) { Icon(Icons.Default.Mic, "Speak", tint = Cyan) }
                    TextField(
                        value = input, onValueChange = { input = it }, modifier = Modifier.weight(1f),
                        placeholder = { Text("Message NOVA…", color = Color(0xFF71819C)) },
                        colors = TextFieldDefaults.colors(
                            focusedContainerColor = Color.Transparent, unfocusedContainerColor = Color.Transparent,
                            focusedTextColor = Color.White, unfocusedTextColor = Color.White,
                            focusedIndicatorColor = Color.Transparent, unfocusedIndicatorColor = Color.Transparent
                        ),
                        maxLines = 4
                    )
                    IconButton(onClick = { sendMessage() }, enabled = !busy) {
                        Icon(Icons.Default.Send, "Send", tint = Cyan)
                    }
                }
            }
        }
        if (showSettings) {
            AlertDialog(
                onDismissRequest = { showSettings = false },
                title = { Text("NOVA • Provider settings", color = Cyan) },
                text = {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("OpenAI-compatible endpoint", fontSize = 12.sp)
                        OutlinedTextField(endpoint, { endpoint = it }, label = { Text("Base URL") }, placeholder = { Text("https://your-provider.example/v1") })
                        OutlinedTextField(model, { model = it }, label = { Text("Model name") })
                        OutlinedTextField(apiKey, { apiKey = it }, label = { Text("API key (stored on this device)") })
                        Divider(color = Color(0xFF33435C))
                        Text("LEARNING & MEMORY", color = Cyan, fontSize = 11.sp, letterSpacing = 1.5.sp)
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text("Speak replies", color = Color.White)
                                Text("Read assistant responses aloud", color = Color.LightGray, fontSize = 10.sp)
                            }
                            Switch(checked = speakReplies, onCheckedChange = { speakReplies = it })
                        }
                        Text("Saved memories (${memories.size})", color = Color.White)
                        if (memories.isEmpty()) Text("No saved memories yet. In chat, type: remember: your preference or fact", color = Color.LightGray, fontSize = 11.sp)
                        else memories.takeLast(5).forEach { Text("• $it", color = Color.LightGray, fontSize = 11.sp) }
                        TextButton(onClick = {
                            memories.clear()
                            prefs.edit().remove("memories").apply()
                        }, enabled = memories.isNotEmpty()) { Text("CLEAR ALL SAVED MEMORIES", color = Color(0xFFFF8A9A)) }
                        Text("NOVA learns through user-approved saved memories and conversation context. It does not retrain its AI model or silently collect personal data. Memory stays on this device and is included in online prompts when relevant.", fontSize = 10.sp, color = Color.LightGray)
                        Text("Use a trusted provider. API credentials are currently stored in app preferences; do not share an APK containing your key.", fontSize = 10.sp, color = Color.LightGray)
                    }
                },
                confirmButton = {
                    TextButton(onClick = {
                        prefs.edit().putString("endpoint", endpoint).putString("model", model)
                            .putString("key", apiKey).putBoolean("speak_replies", speakReplies)
                            .putStringSet("memories", memories.toSet()).apply()
                        showSettings = false
                        status = "Provider settings saved locally"
                    }) { Text("SAVE", color = Cyan) }
                },
                dismissButton = { TextButton(onClick = { showSettings = false }) { Text("CANCEL") } },
                containerColor = Panel
            )
        }
    }
}
