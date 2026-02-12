import os
import json
import requests
import time
from flask import Flask, render_template, request, jsonify
import base64
import random
import csv
from datetime import datetime

# 初始化 Flask 應用
app = Flask(__name__)

# --- API 配置 ---
API_KEY = os.getenv("GEMINI_API_KEY") 
GEMINI_TEXT_MODEL = "gemini-2.5-flash-preview-09-2025" 
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models/"

# --- 核心 AI 呼叫函式 (保持原樣) ---

def call_gemini_api(prompt: str, system_instruction: str) -> str:
    """呼叫 Gemini API，加入重試機制解決 429 錯誤。"""
    if not API_KEY:
        return "回饋失敗：AI 服務未配置 (API Key 缺失)。"

    url = f"{GEMINI_API_BASE}{GEMINI_TEXT_MODEL}:generateContent?key={API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{ "text": system_instruction }]},
        "generationConfig": {"temperature": 0.5}
    }

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            if response.status_code == 429:
                wait_time = (attempt + 1) * 2
                time.sleep(wait_time)
                continue
            response.raise_for_status()
            result = response.json()
            candidate = result.get('candidates', [{}])[0]
            generated_text = candidate.get('content', {}).get('parts', [{}])[0].get('text')
            return generated_text.strip() if generated_text else "回饋失敗：內容生成空值。"
        except Exception as e:
            if attempt == max_retries - 1:
                return "回饋失敗：AI 老師連線異常，請稍後再試。"
            time.sleep(1)
    return "回饋失敗。"

def call_gemini_image_api(user_sentence: str) -> str:
    """呼叫生圖：保持原樣。"""
    if not user_sentence:
        return None
    try:
        seed = int(time.time())
        style_prompt = f"children's book illustration style, simple, cute, {user_sentence}"
        safe_prompt = requests.utils.quote(style_prompt)
        img_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=512&height=512&nologo=true&seed={seed}&model=stable-diffusion-xl"
        response = requests.get(img_url, timeout=30)
        if response.status_code == 200 and response.content:
            return base64.b64encode(response.content).decode('utf-8')
    except Exception as e:
        pass
    return None

# --- 修改後的儲存記錄功能 ---
def save_to_csv(data_dict):
    file_path = 'record.csv'
    # 更新欄位定義，移除舊評分，新增星星與總分欄位
    fieldnames = [
        'timestamp', 'level', 'feedback_round', 'selected_words', 
        'user_sentence', 'ai_feedback', 'word_stars', 'sentence_stars', 'total_stars'
    ]
    
    file_exists = os.path.isfile(file_path)
    try:
        with open(file_path, mode='a', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(data_dict)
    except Exception as e:
        print(f"CSV 寫入失敗: {e}")

# --- AI 輔助功能 (完全保留你原本的 Prompt，只處理標籤) ---
def get_sentence_analysis(user_sentence: str, correct_selected: list, wrong_selected: list, missing_words: list, target_answers: list, sentence_prompt: str) -> str:
    # 決定狀態標頭
    if len(missing_words) == 0 and len(wrong_selected) == 0:
        status_msg = "🌟 太厲害了！你完全觀察正確，找齊了所有單字！"
    else:
        status_msg = "⚠️ 圖片裡還有一些東西你沒發現喔！"

    system_instruction = (
        "你是一位國中一年級英文老師。請根據『原始圖片包含的正確單字』進行回饋。"
        "1. 禁止使用任何 Markdown 符號（如 ** 或 __）。"
        "2. 單字提示：請針對『學生遺漏的所有正確單字』逐一提供外觀、特徵或位置線索，不准說出英文單字本身。"
        "3. 畫面引導：必須嚴格參考『原始圖片正確單字』。每次建議增加一個簡單細節。"
    )

    # 調整 Prompt：移除強制的括號格式，改用描述性要求，避免 AI 變成填空模式
    prompt = (
        f"【事實參考】\n"
        f"圖片中真實存在的正確單字: {', '.join(target_answers)}\n"
        f"學生選中的正確單字: {', '.join(correct_selected)}\n"
        f"學生選錯的單字: {', '.join(wrong_selected)}"
        f"學生遺漏的單字: {', '.join(missing_words)}"
        f"學生目前造句: 『{user_sentence}』\n"
        f"要求句型: 『{sentence_prompt}』\n\n"
        "請務必依照以下編號順序回報，以下三個段落每段之間換一行即可："
        "1. 單字提示：針對遺漏單字提供線索"
        "2. 文法修正：檢查句子文法與單字拼法"
        "3. 畫面引導建議：如何讓句子更接近圖片內容"
    )

    ai_critique = call_gemini_api(prompt, system_instruction)
    
    # 這裡只做一次換行處理，確保 status_msg 跟內容分開
    # 移除 replace 裡的 \n，因為 Gemini 通常會自己換行
    # 我們只確保 1. 之前有一個換行即可
    ai_critique = ai_critique.replace("1. ", "\n1. ")

    final_feedback = f"{ai_critique}"
    # final_feedback = f"{status_msg}{ai_critique}"
    return final_feedback

# --- Flask 路由 ---

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/easy")
def easy_mode():
    return render_template("easy_mode.html")

@app.route("/hard")
def hard_mode():
    return render_template("hard_mode.html")

@app.route("/api/ai_feedback", methods=["POST"])
def get_ai_feedback():
    try:
        data = request.get_json()
        level_idx = data.get('level', 1)
        user_sentence = data.get('user_sentence', '').strip()
        sentence_prompt = data.get('sentence_prompt', '').strip()
        selected_cards = data.get('correct_words', []) 
        round_index = data.get('feedback_count', 0)
        
        # 接收前端算好的星星，並計算總分
        word_stars = int(data.get('word_stars', 0))
        sentence_stars = int(data.get('sentence_stars', 0))
        total_stars = word_stars + sentence_stars

        with open('static/data/easy_mode.json', 'r', encoding='utf-8') as f:
            full_data = json.load(f)
        
        current_level_data = next((item for item in full_data if item["level"] == int(level_idx)), None)
        standard_answers = [a.lower() for a in current_level_data["answer"]] if current_level_data else []
        
        correct_selected = [w for w in selected_cards if w.lower() in standard_answers]
        wrong_selected = [w for w in selected_cards if w.lower() not in standard_answers]
        missing_words = [w for w in standard_answers if w.lower() not in [x.lower() for x in selected_cards]]

        feedback = get_sentence_analysis(
            user_sentence, correct_selected, wrong_selected, 
            missing_words, standard_answers, sentence_prompt
        )

        log_data = {
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'level': level_idx,
            'feedback_round': f"第{round_index + 1}次回饋",
            'selected_words': ",".join(selected_cards),
            'user_sentence': user_sentence,
            'ai_feedback': feedback.replace('\n', ' '),
            'word_stars': word_stars,
            'sentence_stars': sentence_stars,
            'total_stars': total_stars
        }
        save_to_csv(log_data)

        return jsonify({"feedback": feedback})
    except Exception as e:
        return jsonify({"feedback": "伺服器處理錯誤。"}), 500

@app.route("/api/generate_image", methods=["POST"])
def generate_image():
    try:
        data = request.get_json()
        word_stars = int(data.get('word_stars', 0))
        sentence_stars = int(data.get('sentence_stars', 0))

        image_b64 = call_gemini_image_api(data.get('user_sentence', ''))
        if not image_b64:
            return jsonify({"error": "圖片生成失敗"}), 500

        log_data = {
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'level': data.get('level', 1),
            'feedback_round': '生成圖片階段',
            'selected_words': ",".join(data.get('correct_words', [])),
            'user_sentence': data.get('user_sentence', ''),
            'ai_feedback': 'N/A',
            'word_stars': word_stars,
            'sentence_stars': sentence_stars,
            'total_stars': word_stars + sentence_stars
        }
        save_to_csv(log_data)

        return jsonify({"image_data": image_b64})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)