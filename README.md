# zatsugaku

## プロジェクト概要

zatsugakuは、テキストやSRTファイルから音声を合成し、画像や背景音楽と組み合わせて動画を自動生成するPythonスクリプトです。VOICEVOXとFFmpegを使用して、プロジェクトに入力された台本を元に字幕付きの動画を作成します。

## セットアップ方法

1. **リポジトリをクローンします。**

    ```bash
    git clone https://github.com/yourusername/zatsugaku.git
    cd zatsugaku
    ```

2. **Pythonの依存関係をインストールします。**

    仮想環境を作成し、依存関係をインストールすることをお勧めします。

    ```bash
    rye sync
    ```

3. **VOICEVOXの設定**

    - VOICEVOXがローカルで動作していることを確認してください。通常、VOICEVOXは`http://localhost:50021`で動作します。
    - VOICEVOXの最新バージョンを[VOICEVOX公式サイト](https://voicevox.jp/)からダウンロードしてインストールしてください。

4. **FFmpegのインストール**

    FFmpegがインストールされていない場合は、以下のコマンドでインストールします。

    ```bash
    brew install ffmpeg
    ```

## 実行方法

1. **入力ファイルの準備**

    `inputs`ディレクトリに、処理したい台本ファイル（`.txt`または`.srt`）を配置します。

2. **画像の準備**

    `images`ディレクトリに、動画に使用する画像（`.jpg`, `.jpeg`, `.png`, `.bmp`, `.gif`）を配置します。

3. **背景音楽の準備**

    プロジェクトルートに`bgm.mp3`という名前の背景音楽ファイルを配置してください。

4. **スクリプトの実行**

    以下のコマンドを実行して、動画の生成を開始します。

    ```bash
    rye run python main.py
    ```

    スクリプトは、`inputs`ディレクトリ内の台本ファイルを処理し、`output/landscape`および`output/vertical`ディレクトリに横型および縦型の動画を出力します。

## 注意事項

- VOICEVOXのAPIエンドポイントが`http://localhost:50021`であることを確認してください。
- 入力台本ファイルは正しいフォーマット（`.txt`または`.srt`）である必要があります。
- 使用する画像の数が台本のセグメント数と一致していることを確認してください。

## ライセンス

このプロジェクトはMITライセンスの下で公開されています。詳細は`LICENSE`ファイルを参照してください。
