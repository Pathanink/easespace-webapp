import torch
import numpy as np
import json
import logging
import re
import calendar
import time
from datetime import datetime, timedelta, timezone
from services import db, model, tokenizer, device, gemini_model, gemini_enabled
from collections import defaultdict, Counter
from firebase_admin import messaging

logger = logging.getLogger(__name__)

thai_tz = timezone(timedelta(hours=7))

def predict_sentiment(texts, max_length=128):
    if isinstance(texts, str):
        texts = [texts]

    encodings = tokenizer(
        texts,
        truncation=True,
        padding=True,
        max_length=max_length,
        return_tensors='pt'
    )
    input_ids = encodings['input_ids'].to(device)
    attention_mask = encodings['attention_mask'].to(device)

    with torch.no_grad():
        outputs = model(input_ids=input_ids, attention_mask=attention_mask)
        logits = outputs.logits
        probs = torch.softmax(logits, dim=1)
        preds = torch.argmax(probs, dim=1)

    label_map = {0: '🌧ฝนพรำ', 1: '🌤เมฆขาว', 2: '🌞ฟ้าใส'}
    return [label_map[p.item()] for p in preds], probs.cpu().numpy()

def predict_sentiment_with_gemini(text):
    """ใช้ Gemini AI วิเคราะห์อารมณ์"""
    if not gemini_enabled:
        logger.warning("Gemini not enabled, falling back to local model")
        return predict_sentiment(text, model, tokenizer)
    
    try:
        prompt = f"""
วิเคราะห์อารมณ์ของข้อความนี้และจำแนกให้อยู่ในหมวดหมู่ใดหมวดหมู่หนึ่ง:

ข้อความ: "{text}"

กรุณาจำแนกอารมณ์เป็น:
- 🌧ฝนพรำ (อารมณ์แย่ เศร้า หดหู่ เครียด)
- 🌤เมฆขาว (อารมณ์ปกติ เฉยๆ ไม่แย่ไม่ดี)  
- 🌞ฟ้าใส (อารมณ์ดี มีความสุข เบิกบาน)

ตอบกลับในรูปแบบ JSON เท่านั้น โดยใช้อิโมจิและชื่ออารมณ์เท่านั้น ห้ามใส่วงเล็บคำอธิบาย:
{{
    "mood_label": "เลือกจาก: 🌧ฝนพรำ หรือ 🌤เมฆขาว หรือ 🌞ฟ้าใส",
    "confidence": ตัวเลข 0-100
}}

ห้ามใส่ข้อความอื่นนอกจาก JSON
        """
        
        chat_session = gemini_model.start_chat(history=[])
        response = chat_session.send_message(prompt)
        ai_text = response.text
        
        import re
        json_match = re.search(r'\{.*\}', ai_text, re.DOTALL)
        
        if json_match:
            json_str = json_match.group()
            ai_data = json.loads(json_str)
            
            mood_label = ai_data.get('mood_label', '🌤เมฆขาว')
            mood_label = mood_label.strip()
            mood_label = re.sub(r'\s*\([^)]*\)', '', mood_label)
            
            valid_moods = ['🌧ฝนพรำ', '🌤เมฆขาว', '🌞ฟ้าใส']
            if mood_label not in valid_moods:
                if '🌧' in mood_label or 'ฝนพรำ' in mood_label:
                    mood_label = '🌧ฝนพรำ'
                elif '🌞' in mood_label or 'ฟ้าใส' in mood_label:
                    mood_label = '🌞ฟ้าใส'
                else:
                    mood_label = '🌤เมฆขาว'
            
            confidence = float(ai_data.get('confidence', 50))
            
            logger.info(f"Gemini sentiment analysis: {mood_label} ({confidence}%)")
            
            return [mood_label], np.array([[confidence/100]])
        else:
            logger.warning("Could not parse Gemini response as JSON")
            return predict_sentiment(text, model, tokenizer)
            
    except Exception as e:
        logger.error(f"Gemini sentiment analysis error: {e}")
        return predict_sentiment(text, model, tokenizer)


def save_mood_data(user_id, mood_label, journal_text, probability, model_choice='local'):
    """บันทึกข้อมูลอารมณ์ลงฐานข้อมูล"""
    try:
        current_time = datetime.now(thai_tz)
        
        mood_entry = {
            'user_id': user_id,
            'mood_label': mood_label,
            'journal_text': journal_text,
            'probability': float(probability),
            'model_choice': model_choice,
            'timestamp': current_time,
            'date': current_time.strftime('%Y-%m-%d'),
            'created_at': current_time.isoformat()
        }
        
        logger.info(f"Saving mood entry with model: {model_choice}")
        
        doc_ref = db.collection('mood_entries').add(mood_entry)
        
        logger.info(f"Mood data saved successfully with ID: {doc_ref[1].id}")
        return True
            
    except Exception as e:
        logger.error(f"Error saving mood data: {e}")
        return False

def check_today_entry(user_id):
    """ตรวจสอบว่าวันนี้เขียนบันทึกแล้วหรือยัง"""
    try:
        today = datetime.now(thai_tz).strftime('%Y-%m-%d')
        
        entries = db.collection('mood_entries')\
                   .where('user_id', '==', user_id)\
                   .where('date', '==', today)\
                   .limit(1)\
                   .stream()
        
        for entry in entries:
            data = entry.to_dict()
            data['id'] = entry.id  
            return True, data
        
        return False, None
        
    except Exception as e:
        logger.error(f"Error checking today entry: {e}")
        return False, None

def get_today_entry_for_display(user_id):
    """ดึงบันทึกของวันนี้เพื่อแสดง"""
    try:
        has_entry, entry_data = check_today_entry(user_id)
        
        if has_entry and entry_data:
            ts = entry_data.get('timestamp')
            if ts:
                if isinstance(ts, datetime):
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    ts = ts.astimezone(thai_tz)
            else:
                ts = datetime.now(thai_tz)
                
            return {
                'journal_text': entry_data.get('journal_text', ''),
                'mood_label': entry_data.get('mood_label', ''),
                'probability': entry_data.get('probability', 0),
                'timestamp': ts
            }
        return None
    except Exception as e:
        logger.error(f"Error getting today entry: {e}")
        return None

def get_user_settings(user_id):
    """ดึงการตั้งค่าของผู้ใช้"""
    try:
        doc = db.collection('user_settings').document(user_id).get()
        if doc.exists:
            return doc.to_dict()
        else:
            return {
                'notifications': {
                    'daily_reminder': False,
                    'daily_time': '19:00',
                    'weekly_summary': False,
                    'weekly_day': 'sunday',
                    'monthly_phq9': False,
                    'monthly_date': 1
                }
            }
    except Exception as e:
        logger.error(f"Error getting user settings: {e}")
        return {}
    
def get_user_achievements(user_id):
    """ดึงข้อมูล achievements ของผู้ใช้"""
    try:
        entries = db.collection('mood_entries')\
                   .where('user_id', '==', user_id)\
                   .order_by('timestamp')\
                   .stream()
        
        mood_data = []
        for entry in entries:
            data = entry.to_dict()
            mood_data.append(data)
        
        if not mood_data:
            return []
        
        achievements = calculate_achievements(mood_data)
        save_achievements(user_id, achievements)
        
        return achievements
        
    except Exception as e:
        logger.error(f"Error getting achievements: {e}")
        return []

def calculate_achievements(mood_data):
    """คำนวณ achievements จากข้อมูลบันทึก พร้อมวันที่ปลดล็อกที่ถูกต้อง"""
    achievements = []
    
    mood_data.sort(key=lambda x: x['timestamp'])
    
    if not mood_data:
        return []

    simplified_entries = []
    for entry in mood_data:
        mood = entry['mood_label']
        s_mood = mood 
        if '🌞ฟ้าใส' in mood: s_mood = 'ดี'
        elif '🌤เมฆขาว' in mood: s_mood = 'ปกติ'
        elif '🌧ฝนพรำ' in mood: s_mood = 'แย่'
        
        simplified_entries.append({
            'date': entry['timestamp'].strftime('%Y-%m-%d'),
            'mood': s_mood,
            'ts': entry['timestamp']
        })

    achievements.append({
        'id': 'first_step',
        'name': 'First Step',
        'description': 'จดบันทึกครั้งแรก',
        'icon': '🎯',
        'unlocked': True,
        'unlock_date': simplified_entries[0]['date'], 
        'message': 'ก้าวแรกสำคัญเสมอ ✨'
    })

    unique_dates = sorted(list(set(e['date'] for e in simplified_entries)))
    
    streak_milestones = {3: None, 7: None, 30: None} 
    current_streak = 0
    prev_date = None

    for d_str in unique_dates:
        curr_date = datetime.strptime(d_str, '%Y-%m-%d')
        
        if prev_date:
            delta = (curr_date - prev_date).days
            if delta == 1:
                current_streak += 1
            elif delta > 1:
                current_streak = 1 
        else:
            current_streak = 1
            
        prev_date = curr_date
        
        for milestone in streak_milestones:
            if current_streak >= milestone and streak_milestones[milestone] is None:
                streak_milestones[milestone] = d_str 

    streak_configs = [
        {'days': 3, 'id': '3_days_streak', 'name': '3 Days Streak', 'icon': '🔥', 'message': 'เยี่ยมมาก! 🌱'},
        {'days': 7, 'id': '1_week_streak', 'name': '1 Week Streak', 'icon': '⭐', 'message': 'ครบ 7 วันแล้ว 🎉'},
        {'days': 30, 'id': 'consistency_master', 'name': 'Consistency Master', 'icon': '👑', 'message': 'สุดยอด! 🏆'}
    ]

    for conf in streak_configs:
        if streak_milestones[conf['days']]:
            achievements.append({
                'id': conf['id'],
                'name': conf['name'],
                'description': f'จดต่อเนื่อง {conf["days"]} วัน',
                'icon': conf['icon'],
                'unlocked': True,
                'unlock_date': streak_milestones[conf['days']],
                'message': conf['message']
            })

    mood_groups = {'ดี': [], 'ปกติ': [], 'แย่': []}
    for entry in simplified_entries:
        if entry['mood'] in mood_groups:
            mood_groups[entry['mood']].append(entry['date'])

    mood_configs = [
        {'mood': 'ดี', 'id': 'sunny_soul', 'name': 'Sunny Soul ☀️', 'icon': '🌞', 'message': 'หัวใจคุณกำลังเปล่งประกายแสงแดด ☀️'},
        {'mood': 'ปกติ', 'id': 'cloud_walker', 'name': 'Cloud Walker ☁️', 'icon': '☁️', 'message': 'บางวันก็มีเมฆ ☁️'},
        {'mood': 'แย่', 'id': 'rain_survivor', 'name': 'Rain Survivor 🌧', 'icon': '🌧️', 'message': 'คุณเข้มแข็ง 🌧'}
    ]

    for conf in mood_configs:
        count_list = mood_groups[conf['mood']]
        if len(count_list) >= 10:
            achievements.append({
                'id': conf['id'],
                'name': conf['name'],
                'description': f'บันทึกอารมณ์ "{conf["mood"]}" 10 ครั้ง',
                'icon': conf['icon'],
                'unlocked': True,
                'unlock_date': count_list[9], 
                'message': conf['message']
            })

    found_moods = set()
    balanced_unlock_date = None
    
    for entry in simplified_entries:
        if entry['mood'] in ['ดี', 'ปกติ', 'แย่']:
            found_moods.add(entry['mood'])
        
        if len(found_moods) == 3:
            balanced_unlock_date = entry['date']
            break 

    if balanced_unlock_date:
        achievements.append({
            'id': 'balanced_mind',
            'name': 'Balanced Mind ⚖️',
            'description': 'มีการบันทึกครบทั้ง 3 แบบ',
            'icon': '⚖️',
            'unlocked': True,
            'unlock_date': balanced_unlock_date,
            'message': 'สมดุลใจ ⚖️'
        })

    latest_date = simplified_entries[-1]['date'] if simplified_entries else datetime.now(thai_tz).strftime('%Y-%m-%d')

    if check_rainbow_mood(mood_data, [e['mood'] for e in simplified_entries]):
        achievements.append({
            'id': 'rainbow_mood',
            'name': 'Rainbow Mood 🌈',
            'description': 'ในสัปดาห์เดียวกัน มีบันทึกครบทั้ง 3 อารมณ์',
            'icon': '🌈',
            'unlocked': True,
            'unlock_date': latest_date,
            'message': 'คุณเก็บครบทุกสีของอารมณ์ 🌈'
        })

    if check_emotional_marathon(unique_dates):
        achievements.append({
            'id': 'emotional_marathon',
            'name': 'Emotional Marathon 🏃',
            'description': 'จดบันทึกครบทุกวันในเดือนเดียว',
            'icon': '🏃',
            'unlocked': True,
            'unlock_date': latest_date,
            'message': 'สุดยอด! 🏃'
        })

    return achievements

def calculate_max_streak(sorted_dates):
    """คำนวณ streak สูงสุด"""
    if not sorted_dates:
        return 0
    
    max_streak = 1
    current_streak = 1
    
    for i in range(1, len(sorted_dates)):
        prev_date = datetime.strptime(sorted_dates[i-1], '%Y-%m-%d')
        curr_date = datetime.strptime(sorted_dates[i], '%Y-%m-%d')
        
        if (curr_date - prev_date).days == 1:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 1
    
    return max_streak

def check_rainbow_mood(mood_data, simplified_moods):
    """ตรวจสอบ Rainbow Mood achievement"""
    weekly_moods = defaultdict(set)
    
    for i, entry in enumerate(mood_data):
        year, week, _ = entry['timestamp'].isocalendar()
        week_key = f"{year}-W{week:02d}"
        weekly_moods[week_key].add(simplified_moods[i])
    
    for week_moods in weekly_moods.values():
        if {'ดี', 'ปกติ', 'แย่'}.issubset(week_moods):
            return True
    
    return False

def check_emotional_marathon(sorted_dates):
    """ตรวจสอบ Emotional Marathon achievement"""
    if len(sorted_dates) < 28:
        return False
    
    monthly_dates = defaultdict(list)
    
    for date_str in sorted_dates:
        year_month = date_str[:7]
        monthly_dates[year_month].append(date_str)
    
    for month, dates in monthly_dates.items():
        year, month_num = month.split('-')
        year, month_num = int(year), int(month_num)
        
        days_in_month = calendar.monthrange(year, month_num)[1]
        
        if len(dates) >= days_in_month:
            month_dates = [datetime.strptime(d, '%Y-%m-%d').day for d in dates if d.startswith(month)]
            month_dates.sort()
            
            expected_days = list(range(1, days_in_month + 1))
            if month_dates == expected_days[:len(month_dates)]:
                return True
    
    return False

def save_achievements(user_id, achievements):
    """บันทึก achievements ลง Firestore"""
    try:
        doc_ref = db.collection('user_achievements').document(user_id)
        doc_ref.set({
            'achievements': achievements,
            'updated_at': datetime.now(thai_tz),
            'total_unlocked': len(achievements)
        })
        
        logger.info(f"Saved {len(achievements)} achievements for user {user_id}")
        
    except Exception as e:
        logger.error(f"Error saving achievements: {e}")

def check_new_achievements(user_id):
    """ตรวจสอบ achievements ใหม่หลังจากบันทึกอารมณ์"""
    try:
        doc = db.collection('user_achievements').document(user_id).get()
        old_achievements = []
        if doc.exists:
            old_achievements = doc.to_dict().get('achievements', [])
        old_ids = {ach['id'] for ach in old_achievements}

        entries = db.collection('mood_entries')\
                   .where('user_id', '==', user_id)\
                   .order_by('timestamp').stream()
        mood_data = [entry.to_dict() for entry in entries]

        current_achievements = calculate_achievements(mood_data)
        current_ids = {ach['id'] for ach in current_achievements}

        new_achievements = [ach for ach in current_achievements if ach['id'] not in old_ids]

        all_achievements = {ach['id']: ach for ach in old_achievements}
        for ach in new_achievements:
            all_achievements[ach['id']] = ach

        db.collection('user_achievements').document(user_id).set({
            'achievements': list(all_achievements.values()),
            'updated_at': datetime.now(thai_tz),
            'total_unlocked': len(all_achievements)
        })

        return new_achievements

    except Exception as e:
        logger.error(f"Error checking new achievements: {e}")
        return []

def calculate_current_streak(mood_data):
    """คำนวณ Streak ปัจจุบัน (ต่อเนื่องกี่วันจนถึงปัจจุบัน)"""
    if not mood_data:
        return 0

    unique_dates = set()
    for entry in mood_data:
        if 'timestamp' in entry:
            ts = entry['timestamp']
            if hasattr(ts, 'strftime'):
                date_str = ts.strftime('%Y-%m-%d')
            else:
                try:
                    date_str = str(ts)[:10] 
                except:
                    continue
            unique_dates.add(date_str)
            
    sorted_dates = sorted(list(unique_dates), reverse=True)
    
    if not sorted_dates:
        return 0
    
    today = datetime.now(thai_tz).strftime('%Y-%m-%d')
    yesterday = (datetime.now(thai_tz) - timedelta(days=1)).strftime('%Y-%m-%d')
    
    current_streak = 0
    
    if sorted_dates[0] == today:
        check_date = datetime.now(thai_tz)
    elif sorted_dates[0] == yesterday:
        check_date = datetime.now(thai_tz) - timedelta(days=1)
    else:
        return 0 
        
    for i in range(len(sorted_dates)):
        target_date_str = check_date.strftime('%Y-%m-%d')
        
        if target_date_str in unique_dates:
            current_streak += 1
            check_date = check_date - timedelta(days=1)
        else:
            break 
            
    return current_streak

def get_mood_summary_data(user_id, days=30):
    """ดึงข้อมูลสรุปอารมณ์ของผู้ใช้"""
    try:
        start_date = datetime.now(thai_tz) - timedelta(days=days)
        
        logger.info(f"Querying mood data for user: {user_id}, from: {start_date}")
        
        entries = db.collection('mood_entries')\
                    .where('user_id', '==', user_id)\
                    .where('timestamp', '>=', start_date)\
                    .order_by('timestamp')\
                    .stream()
        
        mood_data = []
        for entry in entries:
            data = entry.to_dict()
            data['id'] = entry.id
            mood_data.append(data)
            
        logger.info(f"Found {len(mood_data)} entries")
        
        if len(mood_data) == 0:
            return {
                'line_chart_data': [],
                'pie_chart_data': [],
                'weekly_summary': [],
                'monthly_summary': [],
                'total_entries': 0,
                'period_days': days,
                'current_streak': 0,  
                'longest_streak': 0   
            }
        
        current_streak = calculate_current_streak(mood_data)
        
        unique_dates_list = sorted(list(set(
            entry['timestamp'].strftime('%Y-%m-%d') 
            for entry in mood_data if 'timestamp' in entry
        )))
        longest_streak = calculate_max_streak(unique_dates_list) 

        daily_moods = defaultdict(list)
        mood_counts = Counter()
        
        for entry in mood_data:
            if 'timestamp' not in entry:
                logger.warning(f"Entry missing timestamp: {entry}")
                continue
                
            date_str = entry['timestamp'].strftime('%Y-%m-%d')
            daily_moods[date_str].append({
                'mood': entry['mood_label'],
                'probability': entry['probability']
            })
            mood_counts[entry['mood_label']] += 1
        
        line_chart_data = []
        for date_str in sorted(daily_moods.keys()):
            moods = daily_moods[date_str]
            mood_values = []
            for mood_entry in moods:
                m = mood_entry['mood']
                if 'แย่' in m or 'ฝน' in m:
                    mood_values.append(1)
                elif 'ปกติ' in m or 'เมฆ' in m:
                    mood_values.append(2)
                else:
                    mood_values.append(3)
            
            avg_mood = sum(mood_values) / len(mood_values) if mood_values else 2
            line_chart_data.append({
                'date': date_str,
                'mood_score': round(avg_mood, 2),
                'entries_count': len(moods)
            })
        
        total_entries = sum(mood_counts.values())
        pie_chart_data = []
        for mood, count in mood_counts.items():
            percentage = round((count / total_entries) * 100, 1) if total_entries > 0 else 0
            pie_chart_data.append({
                'mood': mood,
                'count': count,
                'percentage': percentage
            })
        
        weekly_summary = calculate_weekly_summary(mood_data)
        monthly_summary = calculate_monthly_summary(mood_data)
        
        result = {
            'line_chart_data': line_chart_data,
            'pie_chart_data': pie_chart_data,
            'weekly_summary': weekly_summary,
            'monthly_summary': monthly_summary,
            'total_entries': total_entries,
            'period_days': days,
            'current_streak': current_streak, 
            'longest_streak': longest_streak  
        }
        
        logger.info(f"Returning summary with {total_entries} entries, streak: {current_streak}")
        return result
        
    except Exception as e:
        logger.error(f"Error getting mood summary: {e}")
        import traceback
        traceback.print_exc()
        return None
    
    
def calculate_weekly_summary(mood_data):
    """คำนวณสรุปอารมณ์รายสัปดาห์"""
    weekly_data = defaultdict(list)
    
    for entry in mood_data:
        week_key = entry['timestamp'].strftime('%Y-W%U')
        m = entry['mood_label']
        
        if 'แย่' in m or 'ฝน' in m or '🌧' in m:
            mood_score = 1
        elif 'ปกติ' in m or 'เมฆ' in m or '🌤' in m:
            mood_score = 2
        else:
            mood_score = 3
            
        weekly_data[week_key].append(mood_score)
    
    weekly_summary = []
    for week, scores in weekly_data.items():
        avg_score = sum(scores) / len(scores)
        weekly_summary.append({
            'week': week,
            'average_mood': round(avg_score, 2),
            'entries_count': len(scores)
        })
    
    return sorted(weekly_summary, key=lambda x: x['week'])

def calculate_monthly_summary(mood_data):
    """คำนวณสรุปอารมณ์รายเดือน"""
    monthly_data = defaultdict(list)
    
    for entry in mood_data:
        month_key = entry['timestamp'].strftime('%Y-%m')
        m = entry['mood_label']
        
        if 'แย่' in m or 'ฝน' in m or '🌧' in m:
            mood_score = 1
        elif 'ปกติ' in m or 'เมฆ' in m or '🌤' in m:
            mood_score = 2
        else:
            mood_score = 3

        monthly_data[month_key].append(mood_score)
    
    monthly_summary = []
    for month, scores in monthly_data.items():
        year, month_num = month.split('-')
        year_int = int(year)
        month_num_int = int(month_num)
        
        thai_month_names = [
            "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", 
            "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม", 
            "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"
        ]
        month_name = thai_month_names[month_num_int - 1]
        
        thai_year = year_int + 543 
        
        avg_score = sum(scores) / len(scores)
        monthly_summary.append({
            'month': f"{month_name} {thai_year}",
            'month_key': month,
            'average_mood': round(avg_score, 2),
            'entries_count': len(scores)
        })
    
    return sorted(monthly_summary, key=lambda x: x['month_key'])

def get_all_mood_calendar_data(user_id):
    """ดึงข้อมูลวันที่และอารมณ์ทั้งหมดของผู้ใช้สำหรับแสดงบนปฏิทิน"""
    try:
        entries = db.collection('mood_entries')\
                   .where('user_id', '==', user_id)\
                   .order_by('timestamp')\
                   .stream()
        
        calendar_data = {}
        for entry in entries:
            data = entry.to_dict()
            if 'timestamp' in data:
                date_str = data['timestamp'].strftime('%Y-%m-%d')
                if date_str not in calendar_data:
                    calendar_data[date_str] = data['mood_label']
        
        logger.info(f"Generated calendar data with {len(calendar_data)} dates.")
        return calendar_data
        
    except Exception as e:
        logger.error(f"Error getting calendar data: {e}")
        return {}


def get_daily_entry_detail(user_id, date_str):
    """ดึงรายละเอียดบันทึกของวันที่กำหนด"""
    try:
        entries = db.collection('mood_entries')\
                   .where('user_id', '==', user_id)\
                   .where('date', '==', date_str)\
                   .stream()

        daily_entries = []
        for entry in entries:
            data = entry.to_dict()
            
            time_str = '-'
            ts = data.get('timestamp')
            if ts:
                if isinstance(ts, datetime):
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    time_str = ts.astimezone(thai_tz).strftime('%H:%M:%S')
            
            daily_entries.append({
                'id': entry.id,
                'mood_label': data.get('mood_label'),
                'journal_text': data.get('journal_text'),
                'timestamp': time_str
            })
        
        return daily_entries

    except Exception as e:
        logger.error(f"Error getting entry detail for {date_str}: {e}")
        return []

def save_in_app_notification(user_id, title, body, type='alert'):
    try:
        db.collection('user_notifications').add({
            'user_id': user_id,
            'title': title,
            'message': body,
            'type': type, 
            'is_read': False,
            'timestamp': datetime.now(thai_tz)
        })
    except Exception as e:
        print(f"Error saving notification: {e}")

def send_firebase_notification(user_id, title, body):
    """ส่ง Notification ไปยัง Device ของ User"""
    try:
        doc = db.collection('user_tokens').document(user_id).get()
        if not doc.exists:
            return 

        token = doc.to_dict().get('fcm_token')

        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            token=token,
        )

        response = messaging.send(message)
        logger.info(f'Successfully sent message: {response}')

    except Exception as e:
        logger.error(f'Error sending message: {e}')

def send_fcm_message(user_id, title, body):
    try:
        save_in_app_notification(user_id, title, body)

        token_doc = db.collection('user_tokens').document(user_id).get()
        if not token_doc.exists:
            return
        
        token = token_doc.to_dict().get('fcm_token')
        
        import time
        icon_url = f'https://pathanink-easespace-app.hf.space/static/logo.png?v={int(time.time())}'

        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            webpush=messaging.WebpushConfig(
                notification=messaging.WebpushNotification(
                    icon=icon_url,
                    require_interaction=True  
                )
            ),
            token=token,
        )

        messaging.send(message)
        print(f"Sent notification to {user_id}")
    except Exception as e:
        print(f"Error sending to {user_id}: {e}")

last_checked_minute = None

def job_check_settings_and_notify():
    global last_checked_minute 
    
    try:
        now = datetime.now(thai_tz)
        current_time = now.strftime('%H:%M')
        
        if current_time == last_checked_minute:
            return

        last_checked_minute = current_time
        print(f"⏰ Cron: Checking notifications at {current_time}...")
        
        days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        current_day_str = days[now.weekday()] 
        
        current_date_num = now.day 

        all_settings = db.collection('user_settings').stream()
        
        for doc in all_settings:
            user_id = doc.id
            data = doc.to_dict().get('notifications', {})
            
            if data.get('daily_reminder') and data.get('daily_time') == current_time:
                send_fcm_message(user_id, "📝 ถึงเวลาเขียนบันทึก", "วันนี้เป็นไงบ้าง? มาเล่าให้ฟังหน่อยนะ")
                
            if data.get('weekly_summary') and data.get('weekly_day') == current_day_str and current_time == "10:00":
                send_fcm_message(user_id, "📊 สรุปอารมณ์รายสัปดาห์", "มาดูกันว่าสัปดาห์นี้อารมณ์ของคุณเป็นอย่างไร")

            if data.get('monthly_phq9') and int(data.get('monthly_date', 1)) == current_date_num and current_time == "10:00":
                send_fcm_message(user_id, "✨ เช็คสุขภาพใจประจำเดือน", "ได้เวลาทำแบบประเมิน PHQ-9 แล้วค่ะ")
                
    except Exception as e:
        print(f"Scheduler Error: {e}")

def get_admin_mood_stats():
    """(Admin) ดึงข้อมูลย้อนหลัง 7 วัน มาหาค่าเฉลี่ยอารมณ์สำหรับกราฟ"""
    try:
        stats = defaultdict(list)
        today = datetime.now(thai_tz)
        seven_days_ago = today - timedelta(days=7)
        
        docs = db.collection('mood_entries').where('timestamp', '>=', seven_days_ago).stream()
        
        for doc in docs:
            data = doc.to_dict()
            if 'timestamp' not in data or 'mood_label' not in data:
                continue

            date_str = data['timestamp'].strftime('%Y-%m-%d')
            mood_label = data['mood_label']

            score = 2 
            if '🌧' in mood_label or 'ฝน' in mood_label or 'แย่' in mood_label:
                score = 1
            elif '🌞' in mood_label or 'ฟ้า' in mood_label or 'ดี' in mood_label:
                score = 3
            
            stats[date_str].append(score)
        
        labels = []
        values = []
        
        for date in sorted(stats.keys()):
            avg = sum(stats[date]) / len(stats[date])
            labels.append(date)
            values.append(round(avg, 2))
            
        return labels, values

    except Exception as e:
        logger.error(f"Error getting admin mood stats: {e}")
        return [], []

def get_admin_keyword_cloud():
    """(Admin) นับคำที่พบบ่อยในบันทึก (Anonymous)"""
    try:
        all_text = ""
        docs = db.collection('mood_entries').order_by('timestamp', direction='DESCENDING').limit(50).stream()
        
        for doc in docs:
            data = doc.to_dict()
            text = data.get('journal_text', "") 
            if text:
                all_text += " " + text

        words = all_text.split() 
        
        stop_words = [
            'ฉัน', 'ผม', 'เรา', 'เขา', 'เธอ', 'มัน', 'คือ', 'เป็น', 'อยู่', 'จะ', 'ได้', 
            'ให้', 'ใน', 'บน', 'ล่าง', 'แต่', 'ก็', 'แล้ว', 'และ', 'กับ', 'ที่', 'ซึ่ง', 
            'อัน', 'ของ', 'มาก', 'น้อย', 'เลย', 'ครับ', 'ค่ะ', 'นะ', 'จัง', 'วันนี้', 'รู้สึก'
        ]
        
        clean_words = [w for w in words if w not in stop_words and len(w) > 1]
        
        return Counter(clean_words).most_common(20)

    except Exception as e:
        logger.error(f"Error getting admin keywords: {e}")
        return []
    
def run_scheduler():
    print("⏳ Scheduler started: Waiting for the next minute...")
    
    while True:
        now = datetime.now(thai_tz)
        seconds_to_wait = 60 - now.second
        
        time.sleep(seconds_to_wait)
        
        job_check_settings_and_notify()
        
        time.sleep(1)



