# -*- coding: utf-8 -*-
"""
LINE連携会員証システム

機能概要:
1.  LINEユーザーがLINE公式アカウントを通じて会員証登録を行う
2.  ユーザーの名前、地域、メールアドレス、電話番号、会員番号をデータベースに保存
3.  ユーザーがLINE上で会員証情報を確認できる
4.  管理者が登録された会員情報をWebインターフェースで確認できる

技術構成:
* 言語: Python
* フレームワーク: Flask
* データベース: SQLite (ファイルベースの軽量DB)
* LINE Messaging API

開発手順:
1.  FlaskとSQLiteのセットアップ
2.  データベースの設計と作成
3.  LINE Messaging APIの設定
4.  Webhookエンドポイントの実装
5.  会員登録処理の実装
6.  会員証表示処理の実装
7.  管理者用会員情報表示機能の実装

"""

import os
import sqlite3
from flask import Flask, request, jsonify, abort, render_template, url_for, redirect, g, flash
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FollowEvent
import logging
import random
import re
from linebot.models import ButtonsTemplate, URIAction, TemplateSendMessage

# アプリ設定
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'  # セッション管理に必要なSECRET_KEY

# ロギング設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 環境変数からLINE Botの設定情報を取得
# 本番環境では、環境変数に設定することを推奨
YOUR_CHANNEL_ACCESS_TOKEN = os.environ.get('YOUR_CHANNEL_ACCESS_TOKEN')
YOUR_CHANNEL_SECRET = os.environ.get('YOUR_CHANNEL_SECRET')

if YOUR_CHANNEL_ACCESS_TOKEN is None:
    print("環境変数YOUR_CHANNEL_ACCESS_TOKENが設定されていません。")
    YOUR_CHANNEL_ACCESS_TOKEN = "YOUR_CHANNEL_ACCESS_TOKEN"  # デフォルト値を設定 (開発用)
if YOUR_CHANNEL_SECRET is None:
    print("環境変数YOUR_CHANNEL_SECRETが設定されていません。")
    YOUR_CHANNEL_SECRET = "YOUR_CHANNEL_SECRET"  # デフォルト値を設定 (開発用)

line_bot_api = LineBotApi(YOUR_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(YOUR_CHANNEL_SECRET)


# データベース接続
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect('membership.db')
        g.db.row_factory = sqlite3.Row  # カラム名でアクセス可能にする
    return g.db


@app.teardown_appcontext
def close_db(error):
    if 'db' in g:
        g.db.close()


# データベース初期化
def init_db():
    with app.app_context():
        db = get_db()
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()


@app.route('/callback', methods=['POST'])
def callback():
    """
    LINEからのコールバックを処理する
    """
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("Invalid signature. Check your channel secret.")
        abort(400)

    return 'OK'


@handler.add(FollowEvent)
def handle_follow(event):
    """
    友だち追加（またはブロック解除）時の処理
    """
    line_user_id = event.source.user_id
    db = get_db()
    cursor = db.cursor()

    # ユーザーが既に登録されているか確認
    cursor.execute("SELECT * FROM members WHERE line_user_id = ?", (line_user_id,))
    existing_user = cursor.fetchone()

    if not existing_user:
        # 未登録の場合、登録フォームのURLを返す
        register_url = url_for('register', user_id=line_user_id, _external=True)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"会員登録はこちらから: {register_url}")
        )
    else:
        # 登録済みの場合、会員証表示のURLを返す
        show_card_url = url_for('show_member_card', user_id=line_user_id, _external=True)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"会員証はこちらから: {show_card_url}")
        )


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """
    LINEでメッセージを受信した際の処理
    """
    line_user_id = event.source.user_id
    if event.message.text == "会員証登録":
        register_url = url_for('register', user_id=line_user_id, _external=True)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"会員登録はこちらから: {register_url}")
        )
    elif event.message.text == "会員証表示":
        show_card_url = url_for('show_member_card', user_id=line_user_id, _external=True)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"会員証はこちらから: {show_card_url}")
        )
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="「会員証登録」または「会員証表示」と送信してください。")
        )


@app.route('/register', methods=['GET', 'POST'])
def register():
    """
    会員登録フォームの表示と登録処理
    """
    db = get_db()
    cursor = db.cursor()

    if request.method == 'GET':
        line_user_id = request.args.get('user_id')
        return render_template('register.html', user_id=line_user_id)

    elif request.method == 'POST':
        line_user_id = request.form['line_user_id']
        name = request.form['name']
        region = request.form['region']
        email = request.form.get('email')  # 任意項目なのでget()を使用
        phone_number = request.form.get('phone_number')  # 任意項目

        try:
            # バリデーション
            if not name or not region:
                raise ValueError("名前と地域は必須項目です。")
            if email and not re.match(r"[^@]+@[^@]+\.[^@]+", email):
                raise ValueError("メールアドレスの形式が正しくありません。")

            # 会員番号を生成 (例: M0001, M0002...)
            cursor.execute("SELECT MAX(CAST(SUBSTR(member_number, 2) AS INTEGER)) FROM members")
            max_number = cursor.fetchone()[0]
            next_number = 1 if max_number is None else max_number + 1
            member_number = f"M{next_number:04d}"  # M0001, M0002... の形式

            cursor.execute(
                "INSERT INTO members (line_user_id, name, region, email, phone_number, member_number) VALUES (?, ?, ?, ?, ?, ?)",
                (line_user_id, name, region, email, phone_number, member_number)
            )
            db.commit()
            # HTMLを返すように修正
            return render_template('registration_complete.html', message='会員登録が完了しました。', user_id=line_user_id)
        except Exception as e:
            # エラーが発生した場合、ロールバックを行う
            db.rollback()
            app.logger.error(f"Error registering member: {e}")  # エラーログ出力
            return jsonify({'error': '会員登録に失敗しました。', 'message': str(e)}), 500  # エラーメッセージとステータスコードを返す


# 管理者用：会員情報一覧表示
@app.route("/admin/members")
def list_members():
    """
    登録されている会員情報を一覧表示する
    """
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT line_user_id, name, region, email, phone_number, member_number FROM members")
    members = cursor.fetchall()
    return render_template('member_list.html', members=members)


@app.route("/")
def index():
    """
    index.htmlを表示する
    """
    return render_template("index.html")

# 会員証表示
@app.route('/show_member_card')
def show_member_card():
    user_id = request.args.get('user_id')
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT name, region, member_number FROM members WHERE line_user_id = ?", (user_id,))
    member = cursor.fetchone()
    if member:
        name = member['name']
        region = member['region']
        member_number = member['member_number']

        return render_template('show_member_card.html', name=name, region=region, member_number=member_number)
    else:
        return render_template('registration_required.html')


@app.route('/update_profile', methods=['GET', 'POST'])
def update_profile():
    """
    会員情報の更新を行う
    """
    db = get_db()
    cursor = db.cursor()
    user_id = request.args.get('user_id') or request.form.get('line_user_id')

    if not user_id:
        return "user_id is required", 400

    if request.method == 'POST':
        email = request.form['email']
        member_number = request.form['member_number']
        try:
            # バリデーション
            if email and not re.match(r"[^@]+@[^@]+\.[^@]+", email):
                raise ValueError("メールアドレスの形式が正しくありません。")
            if member_number and not member_number.startswith("M"):
                raise ValueError("会員番号の形式が正しくありません。")

            cursor.execute(
                "UPDATE members SET email = ?, member_number = ? WHERE line_user_id = ?",
                (email, member_number, user_id)
            )
            db.commit()
            return render_template('update_complete.html')
        except ValueError as ve:
            db.rollback()
            flash(str(ve)) # エラーメッセージを表示
            return redirect(url_for('update_profile', user_id=user_id)) #元のページへリダイレクト
        except Exception as e:
            db.rollback()
            app.logger.error(f"Error updating profile: {e}")
            return jsonify({'error': '更新失敗', 'message': '会員情報の更新に失敗しました。'}), 500

    else: # GET
        cursor.execute("SELECT email, member_number FROM members WHERE line_user_id = ?", (user_id,))
        member = cursor.fetchone()
        if member:
            email = member['email']
            member_number = member['member_number']
            return render_template('update_profile.html', user_id=user_id, email=email, member_number=member_number)
        else:
            return render_template('registration_required.html') # 登録を促すページを表示

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))