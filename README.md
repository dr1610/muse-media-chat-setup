# Muse Media Chat Setup

[日本語の導入手順](README.ja.md)

Use Muse for text replies, a local TTS server for voice messages, and your local image generator for pictures. The bridge runs on your PC. The starter character is [The Brave Amazon](examples/character.md). Choose a voice from your own TTS installation.

This is a setup preview. Authentication, settings, and WAV/PNG downloads have been checked with test backends. Follow the final test below to verify real generation and playback in your own Muse chat.

## 1. Start your generators

- **English voice.** Follow the [Kokoro setup guide](docs/english-voice.md). It includes a CPU Docker command, an English voice preset and a ready-to-copy configuration.
- **Japanese voice.** Follow the [Irodori-TTS-Server setup guide](https://github.com/Aratako/Irodori-TTS-Server#installation). Start it with `uv run --no-sync python -m irodori_openai_tts --host 127.0.0.1 --port 8088`. Put your own reference audio in its `voices` directory or choose an existing preset. A file named `scout.wav` is selectable as `scout`. The [Irodori v4-Small model](https://huggingface.co/Aratako/Irodori-TTS-v4-Small#-limitations) accepts Japanese speech text.
- **Images.** Start a local WebUI that supports `POST /sdapi/v1/txt2img` and returns PNG images. For [AUTOMATIC1111](https://github.com/AUTOMATIC1111/stable-diffusion-webui/wiki/API), enable `--api`. Use a model that already generates one image in the UI. [SD.Next's API documentation](https://github.com/vladmandic/sdnext/wiki/API) describes the compatible endpoint. For [ComfyUI](https://docs.comfy.org/development/comfyui-server/comms_routes), follow the section below.

## 2. Set up and start the bridge

1. Install Python 3.10 or newer. On Windows, download or extract this repository into a folder and run `setup.cmd`. It installs the bridge dependencies and creates `config.json` and a random key at `data/bridge-key.txt`.
2. Open `config.json` in a text editor. Set `voice.initial_voice` to your preset ID and list it under `voice.allowed_voices`. Add more registered IDs there to switch between them in chat. Enter the local backend URLs if you use different ports. Set a backend's `enabled` to `false` if you are setting up voice or images separately.
3. Run `start.cmd` and leave it open. The bridge listens at `http://127.0.0.1:18790` by default. Edit the sample character file and restart the bridge to change the character or fixed appearance.

On a system with a Python 3.10+ command available, the equivalent terminal setup is:

```sh
python -m venv .venv
# Activate .venv for your shell, then run:
python -m pip install -r requirements.txt
python bridge.py --init
python bridge.py
```

If the Irodori backend requires a Bearer key, set `voice.token_env` to the name of the local environment variable that contains that backend key. Muse uses the separate bridge key.

## 3. Connect Muse and test a reply

1. Connect Muse to your tailnet using its Tailscale integration. Use a port that is free in your Serve configuration. With the default bridge port and a free external port 9443, run:

   ```sh
   tailscale serve --bg --https=9443 http://127.0.0.1:18790
   ```

   Use the HTTPS address printed by Tailscale and grant Muse access to that port. [Muse and Tailscale](https://tailscale.com/blog/meta-muse-ai-agent-tailscale) · [Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve)
2. Create a custom HTTP connector in Muse with that HTTPS base URL. Use the OpenAPI definition at `<base URL>/openapi.json` or upload [the included schema](openapi.json) and set the base URL to your own HTTPS address. Enter the contents of `data/bridge-key.txt` in the connector's Bearer credentials form.
3. Paste [the Muse instructions](docs/muse-instructions.md) into the conversation. Start with one short greeting and one image. Confirm that the image displays and the WAV plays in the chat. Keep the bridge, Tailscale, and selected backends running during use.

## ComfyUI option

1. Use a working text-to-image workflow with a **Save Image** node. Export it in API format and save it beside `bridge.py` as `workflow.json`.
2. In that JSON, replace the positive text encoder's text value with `"__PROMPT__"`. Use `"__NEGATIVE__"` for a negative text input if present. Replace the sampler's seed value with `"__SEED__"` for a new seed each time. Use the placeholders as entire JSON values.
3. Set `image.backend` to `"comfyui"`, `image.url` to the local ComfyUI address (normally `http://127.0.0.1:8188`), and `image.output_node` to the quoted ID of the Save Image node in the exported JSON. Set resolution and model in that workflow. Restart the bridge.

## Chat commands

- “Set voice replies to 30%” saves the voice rate for this chat.
- “This time only, send an image and no voice” changes the next reply only.
- With Irodori, “Use a calm delivery in this chat” saves the acting caption. “Reset caption to automatic” clears it.
- “Switch to the scout voice” works once that preset is in your allowed voice list.

The default is 100% voice, 100% image, and 0% proactive messages. The bridge stores the requested proactive frequency. Sending a message without a user turn needs a separate scheduler connected to Muse. Generated media and local settings are stored in `data/`. Muse receives the text and media used in the conversation.
