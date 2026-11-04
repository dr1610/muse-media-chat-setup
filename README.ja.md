# Museのテキスト・ボイス・画像チャット

[English setup guide](README.md)

Museが会話を担当し、ローカルTTSが音声を、Stable Diffusion WebUIまたはComfyUIが画像を作ります。自分のPCで中継サーバーを起動して、Museへつなぎます。初期キャラは[勇敢なるアマゾネス](examples/character.md)です。

この配布版はプレビューです。認証、設定の保存、WAV・PNG取得はテスト用バックエンドで確認しています。実生成とMuseのチャット内での再生・表示は、手順の最後で確認してください。

1. **生成環境を起動する。** 英語ボイスは[Kokoroの導入手順](docs/english-voice.md#日本語の手順)を使います。日本語ボイスは[Irodori-TTS-Server](https://github.com/Aratako/Irodori-TTS-Server#installation)を導入し、`uv run --no-sync python -m irodori_openai_tts --host 127.0.0.1 --port 8088` で起動します。自分の参照音声を登録して試聴します。画像は、API付きのStable Diffusion WebUIか、[ComfyUI用の手順](README.md#comfyui-option)で準備します。
2. **中継を設定する。** WindowsではPython 3.10以上を入れ、このフォルダの `setup.cmd` を実行します。`config.json` の `voice.initial_voice` に声のIDを、`voice.allowed_voices` に切り替えを許可する声のID一覧を設定します。たとえば `scout.wav` のIDは `scout` です。生成環境のポートが違う場合はURLも変更します。
3. **中継を起動する。** `start.cmd` を開き、TailscaleとMuseを同じネットワークに接続します。例として空いている9443を使う場合、`tailscale serve --bg --https=9443 http://127.0.0.1:18790` で中継専用のHTTPS接続先を作ります。表示されたURLと [OpenAPI定義](openapi.json) をMuseのカスタムHTTPコネクターに登録し、`data/bridge-key.txt` のキーを認証情報フォームへ入れます。
4. **Museで試す。** [Muse用の指示文](docs/muse-instructions.md)を会話に貼り、「焚き火の前で一言挨拶して、写真も送って」と頼みます。会話内で音声が再生でき、画像が表示されるか確認します。

「ボイスは30％に」「今回だけ画像ありで」といった変更は、Museのチャットで指定できます。Irodoriでは「このチャットでは落ち着いて話して」「Captionを自動に戻して」といった演技指定も使えます。初期値はボイス100％・画像100％・自発0％です。自発頻度の値は保存され、自発配信には別途スケジューラーが必要です。
