#!/usr/bin/env python3
import os
import re
import random
import subprocess
import sys
import time
import glob
import shutil

# ===== 定数設定 =====
SPEAKER_ID = 8                   # VOICEVOX の話者ID
IMAGES_DIR = "images"            # 動画用画像ディレクトリ
BGM_FILE = "bgm.mp3"             # 背景音楽ファイル

# 入力台本（テキスト形式）を配置しているディレクトリ
INPUT_DIR = "inputs"
# 出力先のベースディレクトリ
OUTPUT_DIR = "output"
# 横型動画と縦型動画の保存先ディレクトリ
LANDSCAPE_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "landscape")
VERTICAL_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "vertical")

# ===== 新規追加：音声合成用テキスト前処理 =====
def preprocess_for_audio(text):
    """
    音声合成用に、テキスト中の絵文字を読み上げ可能な日本語に変換する
    例: "🐑" を "ひつじ" に変換する
    """
    emoji_map = {
         "🐑": "ひつじ",
         # 必要に応じて他の絵文字変換を追加
    }
    for emoji, reading in emoji_map.items():
         text = text.replace(emoji, reading)
    return text

# ===== ユーティリティ関数 =====
def clear_directory(path):
    """ディレクトリの中身を削除して再生成する"""
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)

def run_ffmpeg(cmd):
    """FFmpeg コマンドを実行するラッパー関数"""
    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        print("ffmpeg エラー:", result.stderr.decode())
        sys.exit(1)

# ===== VOICEVOX 関連 =====
def generate_audio_chunk(text, speaker=SPEAKER_ID, chunk_index=0):
    """VOICEVOX の API を使い、テキストから音声を生成する"""
    os.makedirs("texts", exist_ok=True)
    os.makedirs("query", exist_ok=True)
    os.makedirs("wav", exist_ok=True)

    text_file = f"texts/text_chunk_{chunk_index}.txt"
    query_file = f"query/query_{chunk_index}.json"
    audio_file = f"wav/audio_{chunk_index}.wav"

    with open(text_file, "w", encoding="utf-8") as f:
        f.write(text)
    
    # audio_query の実行（curl で JSON を取得）
    subprocess.run([
        "curl", "-s", "-X", "POST",
        f"localhost:50021/audio_query?speaker={speaker}",
        "--get", "--data-urlencode", f"text@{text_file}",
        "-o", query_file
    ], check=True)
    
    # synthesis の実行（生成した JSON を渡して wav 出力）
    subprocess.run([
        "curl", "-s",
        "-H", "Content-Type: application/json",
        "-X", "POST",
        "-d", f"@{query_file}",
        f"localhost:50021/synthesis?speaker={speaker}",
        "-o", audio_file
    ], check=True)
    
    return audio_file

def get_audio_duration(audio_file):
    """ffprobe を使い、音声ファイルの長さ（秒）を取得する"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", audio_file],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        return float(result.stdout.strip())
    except Exception as e:
        print(f"{audio_file} の長さ取得エラー: {e}")
        return 0.0

def format_srt(entries):
    """タイムスタンプとテキストから SRT フォーマットの文字列を生成する"""
    srt_content = ""
    for i, (start, end, text) in enumerate(entries, start=1):
        start_time = time.strftime('%H:%M:%S', time.gmtime(start)) + f",{int(start % 1 * 1000):03d}"
        end_time = time.strftime('%H:%M:%S', time.gmtime(end)) + f",{int(end % 1 * 1000):03d}"
        srt_content += f"{i}\n{start_time} --> {end_time}\n{text}\n\n"
    return srt_content

def save_srt(content, filename):
    """SRT ファイルとして保存する"""
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

def merge_audio_files(output_file):
    """生成された wav ファイルを結合し MP3 に変換する"""
    wav_files = glob.glob("wav/audio_*.wav")
    wav_files.sort(key=lambda x: int(os.path.basename(x).split('_')[1].split('.')[0]))
    
    if not wav_files:
        print("結合する音声ファイルが見つかりません。")
        return
    
    list_file = "file_list.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for wav in wav_files:
            f.write(f"file '{os.path.abspath(wav)}'\n")
    
    subprocess.run([
        "ffmpeg", "-f", "concat", "-safe", "0", "-i", list_file,
        "-c", "libmp3lame", "-b:a", "192k", output_file, "-y"
    ], check=True)
    
    os.remove(list_file)
    print(f"最終音声: {output_file}")

# ===== SRT パース・変換 =====
def srt_time_to_seconds(time_str):
    """SRT タイムスタンプ（例: "00:01:23,456"）を秒に変換"""
    parts = re.split('[:,]', time_str)
    if len(parts) != 4:
        raise ValueError(f"タイムフォーマットエラー: {time_str}")
    hours, minutes, seconds, millis = parts
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000.0

def parse_srt(srt_path):
    """SRT ファイルをパースして各字幕ブロックの情報を返す"""
    segments = []
    with open(srt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    blocks = re.split(r'\n\s*\n', content.strip())
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) >= 3:
            times = lines[1].strip()
            m = re.match(r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})', times)
            if not m:
                print(f"タイムコード形式エラー: {times}")
                continue
            start_str, end_str = m.groups()
            start = srt_time_to_seconds(start_str)
            end = srt_time_to_seconds(end_str)
            text = " ".join(lines[2:]).replace('"', '\\"')
            segments.append({
                "start": start,
                "end": end,
                "duration": end - start,
                "text": text
            })
    return segments

def read_script_from_srt(srt_path):
    """
    入力の SRT 台本からテキスト部分のみを抽出する。
    ※番号やタイムスタンプは無視し、各ブロックのテキストをまとめて返す。
    """
    segments = []
    with open(srt_path, 'r', encoding='utf-8') as f:
        content = f.read().strip()
    blocks = re.split(r'\n\s*\n', content)
    for block in blocks:
        lines = block.splitlines()
        if len(lines) >= 3:
            text = " ".join(lines[2:]).strip()
            segments.append(text)
        else:
            for line in lines:
                if line.strip() and not re.match(r'^\d+$', line.strip()):
                    segments.append(line.strip())
    return segments

def read_script(script_path):
    """
    汎用的な台本読み込み関数。
    拡張子が .srt の場合は SRT として、.txt の場合は各行をチャンクとして扱います。
    """
    if script_path.lower().endswith(".srt"):
        return read_script_from_srt(script_path)
    elif script_path.lower().endswith(".txt"):
        with open(script_path, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]
    else:
        print(f"未対応のファイル形式: {script_path}")
        return []

# ===== 動画生成 =====
def process_video(srt_file, audio_file, output_video, vertical=False, image_files=None):
    """
    SRT と音声、画像から動画を生成し、字幕を焼き付ける処理  
    vertical: 縦型動画の場合は True, 横型の場合は False
    image_files: 画像ファイルのリスト。Noneの場合は自動で取得する。
    """
    print("SRT ファイルをパース中...")
    segments = parse_srt(srt_file)
    if not segments:
        print("有効なセグメントが SRT ファイルから見つかりません。")
        sys.exit(1)
    
    # 縦型/横型それぞれのスケール・字幕設定
    # ※ 絵文字表示のため、Apple Color Emoji を使用
    if vertical:
        scale_filter = "scale=-1:1920,crop=1080:1920,format=yuv420p"
        # 非カラー絵文字用に、Symbola（または他の非カラー絵文字フォント）を指定する
        subtitle_style = "FontName=Noto Sans CJK JP\\,Symbola,FontSize=24,MarginV=50"
    else:
        scale_filter = "scale=1920:1080,format=yuv420p"
        subtitle_style = subtitle_style = "FontName=Noto Sans CJK JP\\,Symbola,FontSize=30"
    
    # 画像一覧の取得（外部から渡されなければ自動取得）
    if image_files is None:
        valid_ext = ('.jpg', '.jpeg', '.png', '.bmp', '.gif')
        if not os.path.isdir(IMAGES_DIR):
            print(f"画像ディレクトリ '{IMAGES_DIR}' が存在しません。")
            sys.exit(1)
        image_files = [os.path.join(IMAGES_DIR, f) for f in os.listdir(IMAGES_DIR) if f.lower().endswith(valid_ext)]
        if not image_files:
            print("画像ディレクトリ内に有効な画像が見つかりません。")
            sys.exit(1)
        random.shuffle(image_files)
    
    if len(segments) > len(image_files):
        print("セグメント数より画像数が少ないため処理できません。")
        sys.exit(1)
    
    # 各セグメントごとに動画（画像の静止画＋指定時間）を生成
    segment_files = []
    for i, seg in enumerate(segments):
        duration = seg["duration"]
        image_path = image_files[i]
        segment_filename = f"segment_{i:03d}.mp4"
        segment_files.append(segment_filename)
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", image_path,
            "-t", f"{duration:.3f}",
            "-vf", scale_filter,
            "-r", "30",
            "-c:v", "libx264",
            segment_filename
        ]
        print(f"セグメント {i+1}/{len(segments)}: image={image_path}, duration={duration:.3f}s")
        run_ffmpeg(cmd)
    
    # セグメント連結用リスト作成
    concat_list = "segments.txt"
    with open(concat_list, "w", encoding="utf-8") as f:
        for seg_file in segment_files:
            f.write(f"file '{os.path.abspath(seg_file)}'\n")
    
    concat_video = "temp_video.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_list,
        "-c", "copy",
        concat_video
    ]
    run_ffmpeg(cmd)
    
    # BGM を加えた音声合成
    video_audio = "video_with_audio.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-i", concat_video,
        "-i", audio_file,
        "-stream_loop", "-1", "-i", BGM_FILE,
        "-filter_complex", "[1:a]volume=1[a1];[2:a]volume=0.3[a2];[a1][a2]amix=inputs=2:duration=shortest[out]",
        "-map", "0:v",
        "-map", "[out]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        video_audio
    ]
    run_ffmpeg(cmd)
    
    # 字幕を動画に焼き付け（UTF-8 エンコーディングと force_style オプションを追加）
    cmd = [
        "ffmpeg", "-y",
        "-i", video_audio,
        "-vf", f"subtitles={srt_file}:charenc=UTF-8:force_style='{subtitle_style}'",
        "-c:a", "copy",
        output_video
    ]
    run_ffmpeg(cmd)
    print("最終出力動画:", output_video)
    
    # 一時ファイルの削除
    temp_files = segment_files + [concat_list, concat_video, video_audio]
    for f in temp_files:
        if os.path.exists(f):
            os.remove(f)
    print("一時ファイルを削除しました。")

# ===== 台本１件毎の処理 =====
def process_script(script_path):
    """
    指定されたテキスト台本（script_path）から
    音声生成・SRT 再作成・動画作成を実行し、
    横型動画と縦型動画をそれぞれ別ディレクトリに保存します。
    """
    print("=" * 40)
    print(f"台本ファイル: {script_path} を処理します。")
    # 一時ディレクトリのクリア
    for folder in ["texts", "query", "wav"]:
        clear_directory(folder)
    
    # 台本からテキストを抽出（拡張子に応じて）
    lines = read_script(script_path)
    if not lines:
        print(f"{script_path} からテキストが抽出できませんでした。")
        return
    
    srt_entries = []
    current_time = 0.0
    # 各テキストブロックから音声生成とその長さの計測
    for i, line in enumerate(lines):
        print(f"チャンク {i+1}/{len(lines)} 処理中: {line}")
        # 音声合成前に絵文字を変換（例: 🐑 -> ひつじ）
        processed_text = preprocess_for_audio(line)
        audio_file = generate_audio_chunk(processed_text, SPEAKER_ID, i)
        duration = get_audio_duration(audio_file)
        start_time = current_time
        end_time = start_time + duration
        current_time = end_time
        # 字幕は元のテキストを使用（絵文字もそのまま表示）
        srt_entries.append((start_time, end_time, line))
    
    # 生成されたタイミング情報から新たな SRT ファイルを作成
    generated_srt = "generated.srt"
    srt_content = format_srt(srt_entries)
    save_srt(srt_content, generated_srt)
    
    # 全チャンクの音声を結合して１つの MP3 に
    final_audio = "final_audio.mp3"
    merge_audio_files(final_audio)
    
    # 共通の画像ファイルリストを取得して、両方の動画で同じ順番を使用
    valid_ext = ('.jpg', '.jpeg', '.png', '.bmp', '.gif')
    if not os.path.isdir(IMAGES_DIR):
        print(f"画像ディレクトリ '{IMAGES_DIR}' が存在しません。")
        sys.exit(1)
    common_image_files = [os.path.join(IMAGES_DIR, f) for f in os.listdir(IMAGES_DIR) if f.lower().endswith(valid_ext)]
    if not common_image_files:
        print("画像ディレクトリ内に有効な画像が見つかりません。")
        sys.exit(1)
    random.shuffle(common_image_files)
    
    # 横型動画の生成
    landscape_output_temp = "final_output_landscape.mp4"
    process_video(generated_srt, final_audio, landscape_output_temp, vertical=False, image_files=common_image_files)
    
    # 縦型動画（vertical動画）の生成
    vertical_output_temp = "final_output_vertical.mp4"
    process_video(generated_srt, final_audio, vertical_output_temp, vertical=True, image_files=common_image_files)
    
    # タイムスタンプと入力ファイル名（拡張子除く）を利用してファイル名を決定
    timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    input_name = os.path.splitext(os.path.basename(script_path))[0]
    landscape_dest = os.path.join(LANDSCAPE_OUTPUT_DIR, f"{timestamp}_{input_name}_landscape.mp4")
    vertical_dest = os.path.join(VERTICAL_OUTPUT_DIR, f"{timestamp}_{input_name}_vertical.mp4")
    shutil.move(landscape_output_temp, landscape_dest)
    shutil.move(vertical_output_temp, vertical_dest)
    print(f"横型動画を {landscape_dest} に、縦型動画を {vertical_dest} に保存しました。\n")

# ===== メイン処理 =====
def main():
    # ベース出力ディレクトリと横型・縦型用ディレクトリの作成
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(LANDSCAPE_OUTPUT_DIR, exist_ok=True)
    os.makedirs(VERTICAL_OUTPUT_DIR, exist_ok=True)
    print(f"出力先ディレクトリ: {OUTPUT_DIR}")
    
    # inputs ディレクトリ内の .txt ファイル一覧を取得
    script_files = glob.glob(os.path.join(INPUT_DIR, "*.txt"))
    if not script_files:
        print(f"{INPUT_DIR} 内に .txt ファイルが見つかりません。")
        sys.exit(1)
    
    for script in script_files:
        process_script(script)
    
    print("すべての処理が完了しました。")

if __name__ == "__main__":
    main()
