# English voice setup with Kokoro

Kokoro-FastAPI runs on your own PC. It provides English voice presets and returns WAV through the local speech API. The steps below use the project's CPU Docker image. [Kokoro-FastAPI setup and API](https://github.com/remsky/Kokoro-FastAPI#get-started)

1. Start Docker Desktop on Windows, or start Docker Engine on your system. Run this command in a terminal. Port 8880 is available to the local PC.

   ```sh
   docker run -d --name muse-kokoro -p 127.0.0.1:8880:8880 ghcr.io/remsky/kokoro-fastapi-cpu:latest
   ```

2. Open `http://127.0.0.1:8880/docs` in your browser. Under `POST /v1/audio/speech`, select **Try it out** and test this body. The response should contain a WAV.

   ```json
   {
     "model": "kokoro",
     "input": "The campfire is ready. Come sit with me.",
     "voice": "af_heart",
     "response_format": "wav"
   }
   ```

3. Run the bridge's `setup.cmd` if you have not initialized it yet. Open `config.json` in a text editor and replace its `voice` section with the following. Keep the outer JSON object and its other sections.

   ```json
   "voice": {
     "enabled": true,
     "backend": "kokoro",
     "url": "http://127.0.0.1:8880",
     "model": "kokoro",
     "initial_voice": "af_heart",
     "allowed_voices": ["af_heart", "af_bella"],
     "token_env": ""
   }
   ```

4. Start or restart the bridge, then continue with [Connect Muse and test a reply](../README.md#3-connect-muse-and-test-a-reply). Use the bridge's HTTPS URL and key in Muse. Ask Muse to send a short English voice message.

You can choose other English presets from Kokoro's `GET /v1/audio/voices` list and add their IDs to `allowed_voices`. The example uses `af_heart` as a starting preset. Kokoro uses its preset voice and the text you provide. The bridge's free-text acting Caption control is available with Irodori-TTS.

On subsequent starts, run `docker start muse-kokoro`. To stop it, use `docker stop muse-kokoro`.

## 日本語の手順

1. Docker DesktopまたはDocker Engineを起動し、上の `docker run` を実行します。
2. `http://127.0.0.1:8880/docs` を開き、`POST /v1/audio/speech` の **Try it out** で上のテストJSONを送ります。英語のWAVを確認します。
3. 配布版の `config.json` を開き、`voice` の部分を上の設定例に置き換えます。初期プリセットは `af_heart` です。
4. 中継を起動し、[日本語の導入手順](../README.ja.md)に沿ってMuseへ接続します。接続先は中継のHTTPS URLです。Museに「英語で短いボイスメッセージを送って」と頼み、チャット内で再生します。

声を変えたい場合は、Kokoroの `GET /v1/audio/voices` で英語プリセットのIDを確認し、`allowed_voices` に追加します。Kokoroでは声のプリセットと台詞を使います。演技用Captionの指定はIrodori-TTSで利用できます。
