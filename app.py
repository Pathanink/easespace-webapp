from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_from_directory, make_response
from datetime import datetime, timedelta, timezone
import os
import logging
import threading
import time
import traceback
import numpy as np
import csv

from wordcloud import WordCloud        
from pythainlp import word_tokenize    
from pythainlp.corpus import thai_stopwords
import io
import base64  
import random
import json
from firebase_admin import auth

from services import db, auth
from utils import (
    predict_sentiment,
    predict_sentiment_with_gemini,
    save_mood_data,
    check_today_entry,
    get_today_entry_for_display,
    
    get_user_settings,
    
    get_user_achievements,
    check_new_achievements,
    
    get_mood_summary_data,
    get_all_mood_calendar_data,
    get_daily_entry_detail,
    
    save_in_app_notification,
    send_firebase_notification,
    run_scheduler,
    
    get_admin_mood_stats,
    get_admin_keyword_cloud
    
)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

thai_tz = timezone(timedelta(hours=7))

app = Flask(__name__)

app.secret_key = os.getenv('SECRET_KEY', 'easespace-secret-key-for-development-only-change-in-production')

app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)

def get_firebase_config():
    return {
        "apiKey": os.getenv("FIREBASE_API_KEY"),
        "authDomain": os.getenv("FIREBASE_AUTH_DOMAIN"),
        "projectId": os.getenv("FIREBASE_PROJECT_ID"),
        "storageBucket": os.getenv("FIREBASE_STORAGE_BUCKET"),
        "messagingSenderId": os.getenv("FIREBASE_MESSAGING_SENDER_ID"),
        "appId": os.getenv("FIREBASE_APP_ID"),
        "measurementId": os.getenv("FIREBASE_MEASUREMENT_ID")
    }

@app.route('/')
def home(): 
    if "user" not in session:
        return redirect(url_for("login_page"))
    
    user_id = session['user']['uid']
    
    today_entry = get_today_entry_for_display(user_id)
    
    notifications = []
    try:
        notifications_ref = db.collection('user_notifications')\
            .where('user_id', '==', user_id)\
            .where('is_read', '==', False)\
            .order_by('timestamp', direction='DESCENDING')\
            .limit(10)\
            .stream()
        
        for doc in notifications_ref:
            n = doc.to_dict()
            n['id'] = doc.id
            if 'timestamp' in n:
                ts = n['timestamp']
                if isinstance(ts, datetime):
                    if ts.tzinfo is None: 
                        ts = ts.replace(tzinfo=timezone.utc)
                    n['time_str'] = ts.astimezone(thai_tz).strftime('%H:%M')
            notifications.append(n)

    except Exception as e:
        logger.error(f"Error fetching notifications: {e}")

    show_popup = session.pop('show_welcome_popup', False)
    new_achievements = session.pop('new_achievements_popup', None)
    
    result = session.pop('last_analysis_result', None)
    
    if result:
        logger.info(f"Found result to display: {result.get('label')}")
    
    error = session.pop('analysis_error', None)
    
    if error:
        result = {'error': error}
        
    return render_template('index.html', 
                           today_entry=today_entry,
                           notifications=notifications, 
                           new_achievements=new_achievements,
                           show_popup=show_popup,
                           result=result)

@app.route('/login_page')
def login_page():
    return render_template("login.html",fb_config=get_firebase_config())

@app.route('/login', methods=['POST'])
def login():
    try:
        if not request.is_json:
            logger.error("Request is not JSON")
            return jsonify({"error": "Request must be JSON"}), 400
            
        data = request.get_json()
        
        if not data or not data.get("token"):
            logger.error("No token provided")
            return jsonify({"error": "Token is required"}), 400
           
        token = data.get("token")
        
        try:
            decoded_token = auth.verify_id_token(
                token, 
                check_revoked=True,
                clock_skew_seconds=60
            )
            
        except auth.InvalidIdTokenError as e:
            logger.error(f"Invalid ID token: {e}")
            return jsonify({"error": "โทเค็นการยืนยันตัวตนไม่ถูกต้อง กรุณาลองเข้าสู่ระบบใหม่"}), 401
            
        except auth.ExpiredIdTokenError as e:
            logger.error(f"Expired token: {e}")
            return jsonify({"error": "โทเค็นหมดอายุแล้ว กรุณาเข้าสู่ระบบใหม่"}), 401
            
        except auth.RevokedIdTokenError as e:
            logger.error(f"Revoked token: {e}")
            return jsonify({"error": "โทเค็นถูกเพิกถอนแล้ว กรุณาเข้าสู่ระบบใหม่"}), 401
            
        except Exception as e:
            logger.error(f"Token verification error: {e}")
            return jsonify({"error": "ไม่สามารถยืนยันโทเค็นได้ กรุณาลองใหม่"}), 401
        
        uid = decoded_token["uid"]
        email = decoded_token.get("email")
        name = decoded_token.get("name", email)

        user_ref = db.collection('users').document(uid)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            user_ref.set({
                'email': email,
                'name': name,
                'created_at': datetime.now(thai_tz),
                'last_login': datetime.now(thai_tz)
            })

            db.collection('user_notifications').add({
            'user_id': uid,
            'title': 'ขอบคุณที่มาร่วมทดสอบระบบนะ! 🙏',
            'message': 'ดีใจมากที่คุณเข้ามาเป็นส่วนหนึ่งในการพัฒนา EASESPACE ลองเล่นฟีเจอร์ต่างๆ แล้วเขียนบันทึกอารมณ์แรกให้ AI วิเคราะห์ดูหน่อยนะ!',
            'type': 'news',  
            'is_read': False,
            'timestamp': datetime.now(thai_tz)
        })
            
            logger.info(f"New user registered: {email}")
        else:
            user_ref.update({
                'last_login': datetime.now(thai_tz)
            })

        session["user"] = {
            "uid": uid, 
            "email": email,
            "name": name,
            "login_time": datetime.now(thai_tz).isoformat()
        }
        
        session["show_welcome_popup"] = True

        logger.info(f"User logged in successfully: {email}")
        
        return jsonify({
            "success": True, 
            "uid": uid, 
            "email": email,
            "name": name
        })
       
    except Exception as e:
        logger.error(f"Unexpected login error: {str(e)}")
        return jsonify({"error": "เกิดข้อผิดพลาดในการเข้าสู่ระบบ กรุณาลองใหม่อีกครั้ง"}), 500
    
@app.route('/logout')
def logout():
    session.pop("user", None)
    return redirect(url_for("login_page"))

@app.route('/analyze', methods=['POST'])
def analyze():
    if "user" not in session:
        return jsonify({"error": "กรุณาเข้าสู่ระบบก่อน"}), 403

    user_id = session['user']['uid']
    
    journal = request.form.get('journal', '')
    entry_mode = request.form.get('entry_mode', 'ai')

    
    try:
        if entry_mode == 'manual':
            mood_label = request.form.get('manual_mood', '🌤เมฆขาว')
            probability = 100.0 
            analysis_method = "👆 เลือกด้วยตัวเอง"
            model_choice = "manual"
            
            if not journal or not journal.strip():
                journal = "-"

        else:
            if not journal or len(journal.strip()) == 0:
                session['analysis_error'] = 'กรุณาเขียนบันทึกเพื่อให้ AI วิเคราะห์นะคะ ✨'
                return redirect(url_for('home'))
            
            model_choice = request.form.get('model_choice', 'local')
            
            if model_choice == 'gemini':
                pred_labels, pred_probs = predict_sentiment_with_gemini(journal)
                analysis_method = "🤖 Gemini AI"
            else:
                pred_labels, pred_probs = predict_sentiment(journal)
                analysis_method = "🧠 Local AI Model"
                
            mood_label = pred_labels[0]
            probability = np.max(pred_probs[0]) * 100

        has_today_entry, existing_entry = check_today_entry(user_id)
        
        if has_today_entry and existing_entry and 'id' in existing_entry:
             db.collection('mood_entries').document(existing_entry['id']).delete()

        save_success = save_mood_data(user_id, mood_label, journal, probability, model_choice)
        
        if not save_success:
            logger.warning("Failed to save mood data")
        
        new_achievements = check_new_achievements(user_id)
        if new_achievements:
            session['new_achievements_popup'] = new_achievements

        result = {
            'label': mood_label, 
            'probability': f"{probability:.2f}",
            'analysis_method': analysis_method,
            'is_new_entry': True
        }
        session['last_analysis_result'] = result

        return redirect(url_for('home'))
        
    except Exception as e:
        logger.error(f"Analysis error: {e}")
        import traceback
        traceback.print_exc()
        session['analysis_error'] = 'เกิดข้อผิดพลาดในการวิเคราะห์ กรุณาลองใหม่'
        return redirect(url_for('home'))


@app.route('/delete_today_entry', methods=['POST'])
def delete_today_entry():
    """ลบบันทึกของวันนี้"""
    if "user" not in session:
        return jsonify({"error": "กรุณาเข้าสู่ระบบก่อน"}), 403
    
    try:
        user_id = session['user']['uid']
        today = datetime.now(thai_tz).strftime('%Y-%m-%d')
        
        entries = db.collection('mood_entries')\
                   .where('user_id', '==', user_id)\
                   .where('date', '==', today)\
                   .limit(1)\
                   .stream()
        
        deleted_count = 0
        for entry in entries:
            entry.reference.delete()
            deleted_count += 1
            logger.info(f"Deleted entry {entry.id} for user {user_id}")
        
        if deleted_count > 0:
            return jsonify({
                "success": True, 
                "message": "ลบบันทึกเรียบร้อยแล้ว",
                "redirect": "/"
            })
        else:
            return jsonify({
                "success": False,
                "error": "ไม่พบบันทึกที่จะลบ"
            }), 404
            
    except Exception as e:
        logger.error(f"Error deleting entry: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": "เกิดข้อผิดพลาดในการลบบันทึก"
        }), 500
    
@app.route('/mood_summary')
def mood_summary():
    if "user" not in session:
        return redirect(url_for("login_page"))
    
    user_id = session['user']['uid']
    days = int(request.args.get('days', 30))  
    
    summary_data = get_mood_summary_data(user_id, days)
    
    if summary_data is None:
        return render_template('mood_summary.html', error="ไม่สามารถโหลดข้อมูลได้")
    
    return render_template('mood_summary.html', data=summary_data)

@app.route('/api/mood_data')
def api_mood_data():
    if "user" not in session:
        logger.error("User not in session")
        return jsonify({"error": "Unauthorized"}), 403
    
    user_id = session['user']['uid']
    days = int(request.args.get('days', 30))
    
    logger.info(f"Getting mood data for user {user_id}, days: {days}")
    
    summary_data = get_mood_summary_data(user_id, days)
    
    if summary_data is None:
        logger.error("Failed to get summary data")
        return jsonify({"error": "Cannot load data"}), 500
    
    logger.info(f"Returning data: {summary_data.get('total_entries', 0)} entries")
    return jsonify(summary_data)


@app.route('/survey', methods=['GET', 'POST'])
def survey():
    if "user" not in session:
        return redirect(url_for("login_page"))
    result = None
    questions = [
        "ไม่ค่อยสนใจหรือรู้สึกสนุกกับการทำสิ่งต่าง ๆ",
        "รู้สึกเศร้า ซึม หรือสิ้นหวัง",
        "หลับยาก หลับไม่สนิท หรือหลับมากเกินไป",
        "รู้สึกเหนื่อยหรือไม่มีพลังงาน",
        "เบื่ออาหารหรือกินมากเกินไป",
        "รู้สึกแย่กับตัวเองหรือรู้สึกว่าตัวเองล้มเหลว หรือทำให้ตัวเองหรือครอบครัวผิดหวัง",
        "มีปัญหาในการมีสมาธิ เช่น อ่านหนังสือพิมพ์หรือดูโทรทัศน์",
        "เคลื่อนไหวหรือพูดช้ามากจนคนอื่นสังเกตได้ หรืออยู่ไม่สุขหรือกระสับกระส่ายมากกว่าปกติ",
        "คิดว่าตายเสียดีกว่า หรือคิดทำร้ายตัวเองในทางใดทางหนึ่ง"
    ]
    if request.method == 'POST':
        try:
            total_score = 0
            for i in range(1, 10):
                score = int(request.form.get(f'q{i}', 0))
                total_score += score
            
            if total_score <= 4:
                level = "ปกติ"
                emoji = "😊"
                advice = "สุขภาพจิตของคุณอยู่ในเกณฑ์ดีค่ะ คุณดูแลตัวเองได้ดีมากเลย ขอให้มีความสุขและพักผ่อนให้เพียงพอนะคะ 💖"
            elif total_score <= 9:
                level = "เครียดเล็กน้อย"
                emoji = "😐"
                advice = "เป็นเรื่องปกติที่เราจะมีความเครียดเล็กน้อยในชีวิต ลองหาเวลาทำสิ่งที่ชอบ ฟังเพลง หรือออกไปเดินเล่นกับธรรมชาติ ใจเราจะเบาขึ้นค่ะ 🌿"
            elif total_score <= 14:
                level = "เครียดปานกลาง"
                emoji = "😔"
                advice = "คุณอาจรู้สึกเหนื่อยใจไปบ้าง ซึ่งเป็นเรื่องปกติของการใช้ชีวิต ลองพูดคุยกับคนที่เข้าใจ หาเวลาพักผ่อน และอย่าลืมชื่นชมตัวเองที่ผ่านมาได้ถึงวันนี้นะคะ 🌈"
            elif total_score <= 19:
                level = "เครียดมาก"
                emoji = "😰"
                advice = "รู้มั้ยคะว่าการรู้สึกแบบนี้ไม่ใช่ความผิดของคุณ และคุณไม่ได้อยู่คนเดียว ลองปรึกษาผู้เชี่ยวชาญที่จะช่วยดูแลและเข้าใจคุณเพื่อระบายใจก็ได้ค่ะ 🤗"
            else:
                level = "ต้องดูแลเพิ่ม"
                emoji = "😨"
                advice = "คุณกำลังผ่านช่วงเวลาที่ยากลำบาก แต่อย่าลืมว่าทุกปัญหามีทางออก และมีคนที่พร้อมช่วยเหลือคุณ โปรดไปพบแพทย์หรือนักจิตวิทยา พวกเขาจะดูแลคุณด้วยความเข้าใจและไม่ตัดสินค่ะ 💙"
            
            resources = ""
            if total_score >= 10:
                resources = """
                    <ul>
                        <li><a href="tel:1323">สายด่วนสุขภาพจิต: 1323 (24 ชั่วโมง)</a></li>
                        <li><a href="tel:1422">สายด่วนแห่งชีวิต สธ.: 1422</a></li>
                        <li><a href="tel:1667">ศูนย์ปรึกษาปัญหาใจ กรมสุขภาพจิต: 1667</a></li>
                    </ul>
                    """
            
            result = {
                'score': total_score,
                'level': level,
                'emoji': emoji,  
                'advice': advice,
                'resources': resources
            }
        except Exception as e:
            logger.error(f"Survey error: {e}")
            result = {'error': 'เกิดข้อผิดพลาดในการประมวลผล กรุณาลองใหม่'}
    
    return render_template('survey.html', questions=questions, result=result)

@app.route('/settings')
def settings():
    if "user" not in session:
        return redirect(url_for("login_page"))
    
    user_id = session['user']['uid']
    user_settings = get_user_settings(user_id)
    
    return render_template('settings.html', settings=user_settings,fb_config=get_firebase_config())

@app.route('/settings/notifications', methods=['POST'])
def update_notifications():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 403
    
    try:
        user_id = session['user']['uid']
        data = request.get_json()
        
        notification_settings = {
            'daily_reminder': data.get('daily_reminder', False),
            'daily_time': data.get('daily_time', '19:00'),
            'weekly_summary': data.get('weekly_summary', False),
            'weekly_day': data.get('weekly_day', 'sunday'),
            'monthly_phq9': data.get('monthly_phq9', False),
            'monthly_date': data.get('monthly_date', 1),
            'updated_at': datetime.now(thai_tz).isoformat()
        }
        
        db.collection('user_settings').document(user_id).set({
            'notifications': notification_settings
        }, merge=True)
        
        return jsonify({"success": True, "message": "บันทึกการตั้งค่าเรียบร้อย"})
        
    except Exception as e:
        logger.error(f"Error updating notifications: {e}")
        return jsonify({"error": "เกิดข้อผิดพลาด"}), 500

@app.route('/settings/delete_old_data', methods=['POST'])
def delete_old_data():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 403
    
    try:
        user_id = session['user']['uid']
        data = request.get_json()
        days = int(data.get('days', 30))
        
        cutoff_datetime = datetime.now(thai_tz) - timedelta(days=days)
        
        logger.info(f"Deleting entries older than {days} days (before {cutoff_datetime})")
        
        old_entries = db.collection('mood_entries')\
                       .where('user_id', '==', user_id)\
                       .where('timestamp', '<', cutoff_datetime)\
                       .stream()
        
        all_entries = db.collection('mood_entries')\
                       .where('user_id', '==', user_id)\
                       .stream()
        
        total_entries = sum(1 for _ in all_entries)
        
        deleted_count = 0
        batch = db.batch()
        
        for entry in old_entries:
            batch.delete(entry.reference)
            deleted_count += 1
            
            if deleted_count % 500 == 0:
                batch.commit()
                batch = db.batch()
                logger.info(f"Committed batch: {deleted_count} entries")
        
        if deleted_count > 0 and deleted_count % 500 != 0:
            batch.commit()
            logger.info(f"Final commit: {deleted_count} entries deleted")
        
        return jsonify({
            "success": True, 
            "message": f"ลบข้อมูลเก่าแล้ว {deleted_count} รายการ จากทั้งหมด {total_entries} รายการ",
            "deleted_count": deleted_count,
            "total_entries": total_entries,
            "cutoff_date": cutoff_datetime.strftime('%Y-%m-%d %H:%M:%S')
        })
        
    except Exception as e:
        logger.error(f"Error deleting old data: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"เกิดข้อผิดพลาด: {str(e)}"}), 500

@app.route('/debug/delete_data_check')
def debug_delete_data():
    """Debug route เพื่อตรวจสอบข้อมูลก่อนลบ"""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 403
    
    user_id = session['user']['uid']
    days = int(request.args.get('days', 30))
    
    try:
        cutoff_datetime = datetime.now(thai_tz) - timedelta(days=days)
        
        entries = db.collection('mood_entries')\
                   .where('user_id', '==', user_id)\
                   .order_by('timestamp')\
                   .stream()
        
        debug_data = {
            'cutoff_datetime': cutoff_datetime.isoformat(),
            'cutoff_days': days,
            'entries': []
        }
        
        for entry in entries:
            data = entry.to_dict()
            timestamp = data.get('timestamp')
            
            timestamp_str = None
            should_delete = False
            
            if timestamp:
                if hasattr(timestamp, 'timestamp'):
                    timestamp_dt = timestamp
                    timestamp_str = timestamp_dt.strftime('%Y-%m-%d %H:%M:%S')
                    should_delete = timestamp_dt < cutoff_datetime
                elif isinstance(timestamp, str):
                    try:
                        timestamp_dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        if timestamp_dt.tzinfo:
                            timestamp_dt = timestamp_dt.replace(tzinfo=None)
                        timestamp_str = timestamp_dt.strftime('%Y-%m-%d %H:%M:%S')
                        should_delete = timestamp_dt < cutoff_datetime
                    except:
                        timestamp_str = f"Error parsing: {timestamp}"
                elif isinstance(timestamp, datetime):
                    timestamp_dt = timestamp
                    if timestamp_dt.tzinfo:
                        timestamp_dt = timestamp_dt.replace(tzinfo=None)
                    timestamp_str = timestamp_dt.strftime('%Y-%m-%d %H:%M:%S')
                    should_delete = timestamp_dt < cutoff_datetime
            
            debug_data['entries'].append({
                'id': entry.id,
                'mood_label': data.get('mood_label'),
                'timestamp_raw': str(timestamp),
                'timestamp_type': str(type(timestamp)),
                'timestamp_parsed': timestamp_str,
                'should_delete': should_delete,
                'journal_preview': data.get('journal_text', '')[:50] + '...' if data.get('journal_text') else ''
            })
        
        return jsonify(debug_data)
        
    except Exception as e:
        return jsonify({"error": str(e), "traceback": traceback.format_exc()})
        
@app.route('/settings/delete_account', methods=['POST'])
def delete_account():
    if "user" not in session: 
        return jsonify({"error": "Unauthorized"}), 403
    
    try:
        user_id = session['user']['uid']
        data = request.get_json()
        
        if not data.get('confirmed') or data.get('confirmation_text') != 'DELETE MY ACCOUNT':
            return jsonify({"error": "กรุณายืนยันการลบบัญชีโดยพิมพ์ DELETE MY ACCOUNT"}), 400
        
        mood_entries = db.collection('mood_entries').where('user_id', '==', user_id).stream()
        batch = db.batch()
        count = 0
        
        for entry in mood_entries:
            batch.delete(entry.reference)
            count += 1
            if count >= 400: 
                batch.commit()
                batch = db.batch()
                count = 0
        
        if count > 0:
            batch.commit() 
        
        db.collection('user_settings').document(user_id).delete()
        
        auth.delete_user(user_id)
        
        session.clear() 
        
        return jsonify({
            "success": True, 
            "message": "ลบบัญชีเรียบร้อยแล้ว",
            "redirect": url_for("login_page")
        })
        
    except Exception as e:
        logger.error(f"Error deleting account: {e}")
        return jsonify({"error": "เกิดข้อผิดพลาดในการลบบัญชี"}), 500

@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "firebase": "initialized" if db else "no-db",
        "timestamp": datetime.now(thai_tz).isoformat()
    })
    
@app.route('/debug/mood_data')
def debug_mood_data():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 403
    
    user_id = session['user']['uid']
    
    try:
        entries = db.collection('mood_entries')\
                   .where('user_id', '==', user_id)\
                   .order_by('timestamp', direction='DESCENDING')\
                   .limit(10)\
                   .stream()
        
        debug_data = []
        for entry in entries:
            data = entry.to_dict()
            data['id'] = entry.id
            if 'timestamp' in data:
                data['timestamp_str'] = data['timestamp'].isoformat()
            debug_data.append(data)
        
        return jsonify({
            'user_id': user_id,
            'total_found': len(debug_data),
            'latest_entries': debug_data
        })
        
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/achievements')
def achievements():
    """หน้าแสดง achievements"""
    if "user" not in session:
        return redirect(url_for("login_page"))
    
    user_id = session['user']['uid']
    
    user_achievements = get_user_achievements(user_id)
    
    all_achievements = [
        {'id': 'first_step', 'name': 'First Step', 'description': 'จดบันทึกครั้งแรก', 'icon': '🎯'},
        {'id': '3_days_streak', 'name': '3 Days Streak', 'description': 'จดต่อเนื่อง 3 วัน', 'icon': '🔥'},
        {'id': '1_week_streak', 'name': '1 Week Streak', 'description': 'จดครบ 7 วันติด', 'icon': '⭐'},
        {'id': 'consistency_master', 'name': 'Consistency Master', 'description': 'จดครบ 30 วันติด', 'icon': '👑'},
        {'id': 'sunny_soul', 'name': 'Sunny Soul ☀️', 'description': 'บันทึกอารมณ์ "ดี" 10 ครั้ง', 'icon': '🌞'},
        {'id': 'cloud_walker', 'name': 'Cloud Walker ☁️', 'description': 'บันทึกอารมณ์ "ปกติ" 10 ครั้ง', 'icon': '☁️'},
        {'id': 'rain_survivor', 'name': 'Rain Survivor 🌧', 'description': 'บันทึกอารมณ์ "แย่" 10 ครั้ง', 'icon': '🌧️'},
        {'id': 'balanced_mind', 'name': 'Balanced Mind ⚖️', 'description': 'มีการบันทึกครบทั้ง 3 แบบ', 'icon': '⚖️'},
        {'id': 'rainbow_mood', 'name': 'Rainbow Mood 🌈', 'description': 'ในสัปดาห์เดียวกัน มีบันทึกครบทั้ง 3 อารมณ์', 'icon': '🌈'},
        {'id': 'emotional_marathon', 'name': 'Emotional Marathon 🏃', 'description': 'จดบันทึกครบทุกวันในเดือนเดียว', 'icon': '🏃'}
    ]
    
    unlocked_ids = {ach['id'] for ach in user_achievements}
    
    achievements_data = {
        'unlocked': user_achievements,
        'locked': [ach for ach in all_achievements if ach['id'] not in unlocked_ids],
        'total_possible': len(all_achievements),
        'total_unlocked': len(user_achievements),
        'completion_rate': round((len(user_achievements) / len(all_achievements)) * 100, 1)
    }
    
    return render_template('achievements.html', data=achievements_data)

@app.route('/api/achievements')
def api_achievements():
    """API สำหรับดึงข้อมูล achievements"""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 403
    
    user_id = session['user']['uid']
    achievements = get_user_achievements(user_id)
    
    return jsonify({
        'achievements': achievements,
        'total': len(achievements)
    })

@app.route('/game')
def game_play():
    if "user" not in session:
        return redirect(url_for("login_page"))
    
    return render_template("game.html")


@app.route('/api/mood_calendar')
def api_mood_calendar():
    """API สำหรับดึงข้อมูลที่ใช้แสดงในปฏิทิน (วันที่/อารมณ์)"""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 403
    
    user_id = session['user']['uid']
    calendar_data = get_all_mood_calendar_data(user_id)
    
    return jsonify(calendar_data)


@app.route('/api/daily_entry/<string:date_str>')
def api_daily_entry(date_str):
    """API สำหรับดึงรายละเอียดบันทึกของวันนั้น"""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 403
    
    user_id = session['user']['uid']
    daily_entries = get_daily_entry_detail(user_id, date_str)
    
    return jsonify(daily_entries)

@app.route('/api/wordcloud')
def get_wordcloud():
    if "user" not in session: return jsonify({"error": "Unauthorized"}), 403
    user_id = session['user']['uid']
    
    target_mood = request.args.get('mood') 
    days_param = request.args.get('days')

    try:
        query = db.collection('mood_entries').where('user_id', '==', user_id)
        
        if days_param and days_param.isdigit():
            days = int(days_param)
            start_date = datetime.now(thai_tz) - timedelta(days=days)
            query = query.where('timestamp', '>=', start_date)

        if target_mood:
            query = query.where('mood_label', '==', target_mood)
            
        entries = query.stream()
        
        text_content = ""
        for entry in entries:
            data = entry.to_dict()
            if data.get('journal_text'):
                text_content += data.get('journal_text') + " "
        
        if not text_content.strip():
            return jsonify({"image": None, "message": "ไม่มีข้อมูลเพียงพอสำหรับอารมณ์นี้"})

        current_dir = os.path.dirname(os.path.abspath(__file__))
        font_path = os.path.join(current_dir, 'Kanit.ttf') 
        
        if not os.path.exists(font_path):
            return jsonify({"error": "ไม่พบไฟล์ฟอนต์ Kanit.ttf"}), 500

        words = word_tokenize(text_content, engine='newmm')
        stopwords = thai_stopwords()
        custom_stopwords = {' ', '\n', 'ฉัน', 'ผม', 'วันนี้', 'รู้สึก', 'มาก', 'เลย', 'ครับ', 'ค่ะ', 'ก็', 'จะ', 'ที่', 'เป็น', 'ไป'} 
        
        filtered_words = []
        for w in words:
            if w not in stopwords and w not in custom_stopwords and len(w) > 1:
                filtered_words.append(w)
        
        text_for_cloud = " ".join(filtered_words)
        
        if not text_for_cloud:
             return jsonify({"image": None, "message": "คำศัพท์ไม่เพียงพอ"})

        colormap = 'viridis' 
        
        if target_mood == '🌧ฝนพรำ': 
            colormap = 'Blues'   
        elif target_mood == '🌞ฟ้าใส': 
            colormap = 'YlOrBr'  
        elif target_mood == '🌤เมฆขาว': 
            colormap = 'Greens'  
        
        wc = WordCloud(
            font_path=font_path,
            width=800,
            height=400,
            background_color='white',
            colormap=colormap, 
            regexp=r"[ก-๙a-zA-Z']+"
        ).generate(text_for_cloud)
        
        img = io.BytesIO()
        wc.to_image().save(img, format='PNG')
        img.seek(0)
        img_b64 = base64.b64encode(img.getvalue()).decode()
        
        return jsonify({"success": True, "image": f"data:image/png;base64,{img_b64}"})
        
    except Exception as e:
        logger.error(f"Wordcloud error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/save_fcm_token', methods=['POST'])
def save_fcm_token():
    if "user" not in session: return jsonify({"error": "Unauthorized"}), 403
    
    user_id = session['user']['uid']
    token = request.json.get('token')
    
    db.collection('user_tokens').document(user_id).set({
        'fcm_token': token,
        'updated_at': datetime.now(thai_tz)
    }, merge=True)
    
    return jsonify({"success": True})

@app.route('/api/revoke_fcm_token', methods=['POST'])
def revoke_fcm_token():
    if "user" not in session: return jsonify({"error": "Unauthorized"}), 403
    
    user_id = session['user']['uid']
    
    db.collection('user_tokens').document(user_id).delete()
    
    return jsonify({"success": True, "message": "ปิดการแจ้งเตือนเรียบร้อย"})


@app.route('/debug/send_test_noti')
def debug_send_noti():
    if "user" not in session: return "Login first"
    user_id = session['user']['uid']
    
    send_firebase_notification(user_id, "สวัสดีจาก Flask!", "นี่คือแจ้งเตือนผ่าน Firebase จ้า 🎉")
    return "Sent!"

@app.route('/firebase-messaging-sw.js')
def firebase_messaging_sw():
    response = make_response(render_template('firebase-messaging-sw.js', fb_config=get_firebase_config()))
    response.headers['Content-Type'] = 'application/javascript'
    return response

@app.route('/api/mark_read/<noti_id>', methods=['POST'])
def mark_notification_read(noti_id):
    if "user" not in session: return jsonify({"error": "Unauthorized"}), 403
    try:
        db.collection('user_notifications').document(noti_id).update({'is_read': True})
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

@app.route('/api/delete_entry/<entry_id>', methods=['POST'])
def delete_specific_entry(entry_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 403
    
    try:
        db.collection('mood_entries').document(entry_id).delete()
        
        return jsonify({"success": True, "message": "ลบเรียบร้อย"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/export_data')
def export_data():
    if "user" not in session:
        return redirect(url_for("login_page"))
    
    user_id = session['user']['uid']
    
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    
    try:
        query = db.collection('mood_entries').where('user_id', '==', user_id)
        
        is_filtered = False
        
        if start_str and end_str:
            try:
                start_dt = datetime.strptime(start_str, '%Y-%m-%d')
                end_dt = datetime.strptime(end_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            
                query = query.where('timestamp', '>=', start_dt)\
                             .where('timestamp', '<=', end_dt)
                is_filtered = True
            except ValueError:
                pass 

        docs = query.stream()
        
        all_entries = []
        for doc in docs:
            entry = doc.to_dict()
            if entry.get('timestamp'):
                all_entries.append(entry)
    
        all_entries.sort(key=lambda x: x['timestamp'], reverse=True)
        
        si = io.StringIO()
        cw = csv.writer(si)
        
        cw.writerow(['Date', 'Time', 'Mood', 'Journal Text', 'Confidence (%)', 'AI Model'])
        
        for data in all_entries:
            ts = data.get('timestamp')
            date_str = '-'
            time_str = '-'
            
            if ts:
                if isinstance(ts, datetime):
                    thai_ts = ts + timedelta(hours=7)
                    date_str = thai_ts.strftime('%Y-%m-%d')
                    time_str = thai_ts.strftime('%H:%M:%S')
            
            cw.writerow([
                date_str,
                time_str,
                data.get('mood_label', '-'),
                data.get('journal_text', '-'),
                f"{data.get('probability', 0):.2f}",
                data.get('model_choice', 'unknown')
            ])
            
        output = make_response('\ufeff' + si.getvalue())
        
        filename = "mood_history_all.csv"
        if is_filtered:
            filename = f"mood_history_{start_str}_to_{end_str}.csv"
            
        output.headers["Content-Disposition"] = f"attachment; filename={filename}"
        output.headers["Content-type"] = "text/csv; charset=utf-8"
        
        return output

    except Exception as e:
        logger.error(f"Export error: {e}")
        return f"เกิดข้อผิดพลาดในการ Export: {str(e)}"

@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    ADMIN_USER = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "123456")

    if not session.get('is_admin_logged_in'):
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            
            if username == ADMIN_USER and password == ADMIN_PASS:
                session['is_admin_logged_in'] = True
                return redirect('/admin')
            else:
                return """
                <!DOCTYPE html>
                <html lang="th">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>Login Error</title>
                    <link href="https://fonts.googleapis.com/css2?family=Kanit:wght@300;400;600&display=swap" rel="stylesheet">
                    <style>
                        body { background: #FFF9E6; font-family: 'Kanit', sans-serif; height: 100vh; display: flex; align-items: center; justify-content: center; margin: 0; }
                        .error-card { background: white; padding: 40px; border-radius: 20px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); text-align: center; max-width: 400px; width: 90%; border: 1px solid rgba(255,0,0,0.1); }
                        .btn-back { display: inline-block; margin-top: 25px; padding: 12px 30px; background: linear-gradient(135deg, #FFD700, #FFA500); color: #333; text-decoration: none; border-radius: 25px; font-weight: 600; box-shadow: 0 4px 15px rgba(255, 165, 0, 0.3); transition: 0.3s; }
                        .btn-back:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(255, 165, 0, 0.4); }
                    </style>
                </head>
                <body>
                    <div class="error-card">
                        <div style="font-size: 60px; margin-bottom: 20px;">❌</div>
                        <h2 style="color: #FF4757; margin: 0 0 10px 0;">รหัสผ่านไม่ถูกต้อง!</h2>
                        <p style="color: #666;">ชื่อผู้ใช้หรือรหัสผ่านผิด<br>กรุณาตรวจสอบแล้วลองใหม่อีกครั้ง</p>
                        <a href='/admin' class="btn-back">ลองใหม่</a>
                    </div>
                </body>
                </html>
                """
        
        return """
        <!DOCTYPE html>
        <html lang="th">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Admin Login</title>
            <link href="https://fonts.googleapis.com/css2?family=Kanit:wght@300;400;600&display=swap" rel="stylesheet">
            <style>
                body {
                    background: #FFF9E6;
                    font-family: 'Kanit', sans-serif;
                    height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin: 0;
                }
                .login-card {
                    background: #FFFFF0;
                    padding: 40px;
                    border-radius: 20px;
                    box-shadow: 0 10px 30px rgba(0,0,0,0.1);
                    width: 90%;
                    max-width: 400px;
                    text-align: center;
                    border: 1px solid rgba(255, 215, 0, 0.2);
                }
                .login-icon { 
                    width: 80px; height: 80px; background: #FFF9E6; border-radius: 50%; 
                    display: flex; align-items: center; justify-content: center; 
                    font-size: 40px; margin: 0 auto 20px;
                    box-shadow: 0 4px 10px rgba(0,0,0,0.05);
                }
                h2 { color: #333; margin: 0 0 5px 0; font-weight: 600; }
                p { color: #888; margin: 0 0 30px 0; font-size: 0.9rem; }
                
                input {
                    width: 100%;
                    padding: 12px 15px;
                    margin-bottom: 15px;
                    border: 1px solid #FFE082;
                    border-radius: 12px;
                    background: #FFFDE7;
                    font-family: 'Kanit';
                    font-size: 1rem;
                    box-sizing: border-box;
                    outline: none;
                    transition: 0.3s;
                }
                input:focus { border-color: #FFA500; background: white; box-shadow: 0 0 0 3px rgba(255, 165, 0, 0.2); }
                
                button {
                    width: 100%;
                    padding: 12px;
                    margin-top: 10px;
                    background: linear-gradient(135deg, #FFD700, #FFA500);
                    color: #333;
                    border: none;
                    border-radius: 25px;
                    font-size: 1rem;
                    font-weight: 600;
                    cursor: pointer;
                    transition: 0.3s;
                    box-shadow: 0 4px 15px rgba(255, 165, 0, 0.3);
                }
                button:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(255, 165, 0, 0.4); background: linear-gradient(135deg, #FFA500, #FFD700); }
                
                .back-link { display: block; margin-top: 25px; color: #999; text-decoration: none; font-size: 0.9rem; transition: 0.3s; }
                .back-link:hover { color: #FFA500; }
            </style>
        </head>
        <body>
            <div class="login-card">
                <div class="login-icon">🔐</div>
                <h2>Admin Login</h2>
                <p>เข้าสู่ระบบจัดการ EASESPACE</p>
                
                <form method="POST">
                    <input type="text" name="username" required placeholder="ชื่อผู้ใช้ (Username)">
                    <input type="password" name="password" required placeholder="รหัสผ่าน (Password)">
                    <button type="submit">เข้าสู่ระบบ</button>
                </form>
                
                <a href="/" class="back-link">← กลับหน้าหลัก</a>
            </div>
        </body>
        </html>
        """

    broadcast_success = False
    broadcast_count = 0
    error_message = None

    if request.method == 'POST':
        if request.form.get('action') == 'logout':
            session.pop('is_admin_logged_in', None)
            return redirect('/admin')

        title = request.form.get('title')
        message = request.form.get('message')
        msg_type = request.form.get('type', 'news')

        try:
            batch = db.batch()
            users = auth.list_users().iterate_all()
            count = 0
            for user in users:
                ref = db.collection('user_notifications').document()
                batch.set(ref, {
                    'user_id': user.uid,
                    'title': title,
                    'message': message,
                    'type': msg_type,
                    'is_read': False,
                    'timestamp': datetime.now(thai_tz)
                })
                count += 1
                if count % 400 == 0:
                    batch.commit()
                    batch = db.batch()
            if count > 0:
                batch.commit()
            
            broadcast_success = True
            broadcast_count = count
        except Exception as e:
            error_message = f"เกิดข้อผิดพลาด: {str(e)}"

    system_status = "Online"
    try:
        db.collection('user_settings').limit(1).get()
    except:
        system_status = "Offline"

    mood_labels, mood_values = get_admin_mood_stats()
    keywords = get_admin_keyword_cloud()
    
    user_count = 0
    try:
        all_users = auth.list_users().iterate_all()
        user_count = sum(1 for _ in all_users)
        
    except Exception as e:
        print(f"Error counting users: {e}")
    
    user_count = 0
    active_count = 0
    inactive_count = 0
    
    try:
        all_users = auth.list_users().iterate_all()
        
        cutoff_date = datetime.now(thai_tz) - timedelta(days=30)
        
        for user in all_users:
            user_count += 1
            
            last_login_ms = user.user_metadata.last_sign_in_timestamp
            
            if last_login_ms:
                last_login_date = datetime.fromtimestamp(last_login_ms / 1000.0, tz=timezone.utc)
                
                if last_login_date > cutoff_date:
                    active_count += 1
                else:
                    inactive_count += 1
            else:
                inactive_count += 1
                
    except Exception as e:
        print(f"Error counting users: {e}")

    return render_template('admin_dashboard.html',
                           status=system_status,
                           mood_labels=json.dumps(mood_labels),
                           mood_values=json.dumps(mood_values),
                           keywords=keywords,
                           success=broadcast_success,
                           count=broadcast_count,
                           error=error_message,
                           user_count=user_count,
                           active_count=active_count,
                           inactive_count=inactive_count)

@app.route('/api/notification_count')
def api_notification_count():
    if 'user' not in session:
        return jsonify({'count': 0})
    
    user_id = session['user']['uid']
    
    docs = db.collection('user_notifications')\
             .where('user_id', '==', user_id)\
             .where('is_read', '==', False)\
             .stream()
             
    count = sum(1 for _ in docs)
    return jsonify({'count': count})

@app.route('/api/get_notifications')
def api_get_notifications():
    if 'user' not in session:
        return jsonify([])
    
    user_id = session['user']['uid']
    
    docs = db.collection('user_notifications')\
             .where('user_id', '==', user_id)\
             .where('is_read', '==', False)\
             .order_by('timestamp', direction='DESCENDING')\
             .stream()
             
    notis = []
    for doc in docs:
        data = doc.to_dict()
        
        time_str = ''
        if data.get('timestamp'):
            ts = data['timestamp']
            if isinstance(ts, datetime):
                if ts.tzinfo is None: 
                    ts = ts.replace(tzinfo=timezone.utc)
                time_str = ts.astimezone(thai_tz).strftime('%H:%M น.')

        notis.append({
            'id': doc.id,
            'title': data.get('title', ''),
            'message': data.get('message', ''),
            'type': data.get('type', 'info'),
            'time_str': time_str
        })
    
    return jsonify(notis)

@app.route('/admin/export_csv')
def admin_export_csv():
    if not session.get('is_admin_logged_in'):
        return redirect('/admin')

    try:
        docs = db.collection('mood_entries').order_by('timestamp', direction='DESCENDING').stream()
        
        si = io.StringIO()
        cw = csv.writer(si)
        
        cw.writerow(['Date', 'Time', 'User ID', 'Mood Label', 'Probability', 'Note'])
        
        for doc in docs:
            data = doc.to_dict()
            ts = data.get('timestamp')
            
            date_str = '-'
            time_str = '-'
            if ts:
                if isinstance(ts, datetime):
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    thai_ts = ts.astimezone(thai_tz)
                    date_str = thai_ts.strftime('%Y-%m-%d')
                    time_str = thai_ts.strftime('%H:%M:%S')
            
            cw.writerow([
                date_str,
                time_str,
                data.get('mood_label', '-'),
                f"{data.get('probability', 0):.2f}"
            ])

        csv_content = '\ufeff' + si.getvalue()
        
        output = make_response(csv_content)
        output.headers["Content-Disposition"] = "attachment; filename=mood_statistics.csv"
        output.headers["Content-type"] = "text/csv; charset=utf-8"
        
        return output

    except Exception as e:
        return f"Error exporting CSV: {e}"
    
if __name__ == '__main__':
    import os
    
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        print("🚀 Starting Scheduler (Background Task)...")
        t = threading.Thread(target=run_scheduler)
        t.daemon = True
        t.start()
    else:
        print("ℹ️ Main Process started. Waiting for reloader...")

    app.run(debug=True, host='0.0.0.0', port=5000)