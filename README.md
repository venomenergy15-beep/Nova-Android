# NOVA Android Starter

A first Android-native foundation for the NOVA personal assistant.

## Included in this milestone
- Futuristic dark Compose interface.
- Text chat UI.
- Android speech recognition intent for voice input.
- Android Text-to-Speech output plumbing (automatic reply speaking is not wired yet).
- Configurable OpenAI-compatible `/chat/completions` endpoint, model, and API key.
- Local preferences for provider settings.
- Explicit offline-mode selector placeholder.

## Not yet implemented
- A bundled offline language model / local inference runtime.
- Durable conversation memory and searchable notes.
- Automatic TTS playback of assistant responses.
- Web search tools, file import, image understanding/generation, and device automations.
- Production-grade encrypted API-key storage, streaming, retries, and provider-specific adapters.

## Build
Open this folder in Android Studio (recent stable version), allow Gradle sync, then build the `app` configuration.
The project has not been compiled or tested on a physical device as part of this starter delivery.

## Provider setup
In NOVA Settings, enter an OpenAI-compatible API base URL (for example a provider's `/v1` base URL), model name, and API key. NOVA appends `/chat/completions`.
Do not hard-code private API keys into source code or distribute an APK containing your key.

## Self-learning design
NOVA's current learning feature is deliberately user-controlled: type `remember: ...` in chat to save a fact or preference locally. Type `forget all memories` to erase saved memory. Saved items are supplied as context to the online model. This is personalization/retrieval, not model-weight training. True on-device model fine-tuning is not included and would require a compatible model, substantial storage/RAM, and a separate training pipeline.

## Build an APK using only an Android phone (GitHub cloud build)

This project includes `.github/workflows/build-apk.yml`. You can use GitHub Actions to compile it in the cloud; no PC or Android Studio is required.

1. In your phone browser, sign in to GitHub and create a **new repository** named `NOVA-Android`. A private repository is fine.
2. Extract this ZIP on your phone. In the extracted project, upload the project files and folders to the repository root. Make sure the `.github/workflows/build-apk.yml` file is included. If your file picker hides folders beginning with a dot, use GitHub's **Add file → Create new file** and create `.github/workflows/build-apk.yml`, then paste in the workflow from this project.
3. Open the repository's **Actions** tab. If GitHub asks, enable Actions for the repository.
4. Select **Build NOVA APK** → **Run workflow** → **Run workflow**.
5. Wait for the run to finish with a green check. Open that run, scroll to **Artifacts**, and download `NOVA-debug-apk`.
6. Extract the downloaded artifact ZIP. Tap `app-debug.apk` and follow Android's install prompts. Android may ask you to allow installs from your browser or file manager.

The workflow builds a debug APK for testing. It does not publish NOVA to the Play Store. Keep API keys private; do not commit real keys into the repository.
