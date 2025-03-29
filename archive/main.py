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

# 入力台本（SRT形式）を配置しているディレクトリ
INPUT_SRT_DIR = "subs"
# 出力先のディレクトリ（各出力ファイルは output/{timestamp}.mp4 となる）
OUTPUT_DIR = "output"

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

# ===== 動画生成 =====
def process_video(srt_file, audio_file, output_video):
    """
    SRT と音声、画像から動画を生成し、字幕を焼き付ける処理  
    （srt_file, audio_file は先に生成したものを利用）
    """
    print("SRT ファイルをパース中...")
    segments = parse_srt(srt_file)
    if not segments:
        print("有効なセグメントが SRT ファイルから見つかりません。")
        sys.exit(1)

    # 画像ディレクトリから画像一覧取得
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
            "-vf", "scale=1920:1080,format=yuv420p",
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

    # 字幕を動画に焼き付け
    cmd = [
        "ffmpeg", "-y",
        "-i", video_audio,
        "-vf", f"subtitles={srt_file}:force_style='FontName=Noto Sans CJK JP,FontSize=30'",
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
def process_script(script_path, output_dir):
    """
    指定された SRT 台本（script_path）から
    音声生成・SRT 再作成・動画作成を実行し、
    出力動画を output_dir に保存する。
    """
    print("=" * 40)
    print(f"台本ファイル: {script_path} を処理します。")
    # 一時ディレクトリのクリア
    for folder in ["texts", "query", "wav"]:
        clear_directory(folder)
    
    # 台本からテキストを抽出（ブロック単位）
    lines = read_script_from_srt(script_path)
    if not lines:
        print(f"{script_path} からテキストが抽出できませんでした。")
        return

    srt_entries = []
    current_time = 0.0
    # 各テキストブロックから音声生成とその長さの計測
    for i, line in enumerate(lines):
        print(f"チャンク {i+1}/{len(lines)} 処理中: {line}")
        audio_file = generate_audio_chunk(line, SPEAKER_ID, i)
        duration = get_audio_duration(audio_file)
        start_time = current_time
        end_time = start_time + duration
        current_time = end_time
        srt_entries.append((start_time, end_time, line))
    
    # 生成されたタイミング情報から新たな SRT ファイルを作成
    generated_srt = "generated.srt"
    srt_content = format_srt(srt_entries)
    save_srt(srt_content, generated_srt)
    
    # 全チャンクの音声を結合して１つの MP3 に
    final_audio = "final_audio.mp3"
    merge_audio_files(final_audio)
    
    # 動画生成（生成した SRT と音声を使用）
    output_video_temp = "final_output.mp4"
    process_video(generated_srt, final_audio, output_video_temp)
    
    # ファイル名はその時のタイムスタンプを使用（例：20250306_123456.mp4）
    timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    dest_video = os.path.join(output_dir, f"{timestamp}.mp4")
    shutil.move(output_video_temp, dest_video)
    print(f"動画を {dest_video} に保存しました。\n")

# ===== メイン処理 =====
def main():
    # 出力先ディレクトリ OUTPUT_DIR が存在しなければ作成
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"出力先ディレクトリ: {OUTPUT_DIR}")

    # subs ディレクトリ内の .srt ファイル一覧を取得
    script_files = glob.glob(os.path.join(INPUT_SRT_DIR, "*.srt"))
    if not script_files:
        print(f"{INPUT_SRT_DIR} 内に .srt ファイルが見つかりません。")
        sys.exit(1)
    
    for script in script_files:
        process_script(script, OUTPUT_DIR)
    
    print("すべての処理が完了しました。")

if __name__ == "__main__":
    main()
