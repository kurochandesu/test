# -*- coding: utf-8 -*-
"""
LINE連携会員証システム

機能概要:
1.  LINEユーザーがLINE公式アカウントを通じて会員証登録を行う
2.  ユーザーのLINE ID、名前、地域、メールアドレス、電話番号をデータベースに保存
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
from flask import Flask, request, jsonify, abort, render_template, url_for, redirect, g
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# アプリ設定
app = Flask(__name__)

# 環境変数からLINE Botの設定情報を取得
# 本番環境では、環境変数に設定することを推奨
YOUR_CHANNEL_ACCESS_TOKEN = os.environ.get('YOUR_CHANNEL_ACCESS_TOKEN')
YOUR_CHANNEL_SECRET = os.environ.get('YOUR_CHANNEL_SECRET')

if YOUR_CHANNEL_ACCESS_TOKEN is None:
    print("環境変数YOUR_CHANNEL_ACCESS_TOKENが設定されていません。")
    YOUR_CHANNEL_ACCESS_TOKEN = "YOUR_CHANNEL_ACCESS_TOKEN"  # デフォルト値を設定
if YOUR_CHANNEL_SECRET is None:
    print("環境変数YOUR_CHANNEL_SECRETが設定されていません。")
    YOUR_CHANNEL_SECRET = "YOUR_CHANNEL_SECRET"  # デフォルト値を設定

line_bot_api = LineBotApi(YOUR_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(YOUR_CHANNEL_SECRET)

# データベース設定
DATABASE_PATH = 'membership.db'

def get_db():
    """
    アプリケーションコンテキスト内でデータベース接続を管理する。
    """
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE_PATH)
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    """
    アプリケーションコンテキスト終了時にデータベース接続を閉じる。
    """
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    """
    データベースを初期化する（テーブル作成など）。
    """
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS members (
                line_user_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,       -- 追加：名前
                region TEXT NOT NULL,     -- 追加：地域
                email TEXT,              -- 任意
                phone_number TEXT,       -- 任意
                member_number TEXT
            )
        ''')
        db.commit()

# アプリ起動時にデータベースを初期化
with app.app_context():
    init_db()


# Webhookエンドポイント
@app.route("/callback", methods=['POST'])
def callback():
    """
    LINEからのWebhookリクエストを処理する
    """
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'


# メッセージイベントハンドラー
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """
    LINEからのメッセージイベントを処理する
    """
    user_id = event.source.user_id
    message_text = event.message.text

    app.logger.info(f"User ID: {user_id}, Message: {message_text}")  # ログ出力

    if message_text == "会員証登録":
        # 登録フォームのURLを送信する
        # Flaskのurl_for関数を使ってURLを生成する
        register_url = url_for('register_form', user_id=user_id, _external=True)
        reply_text = f"以下のURLから会員情報を登録してください。\n{register_url}"
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
    elif message_text == "会員証表示":
        # データベースから会員情報を取得して表示
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT name, region, email, phone_number, member_number FROM members WHERE line_user_id = ?", (user_id,))
        row = cursor.fetchone()

        if row:
            name, region, email, phone_number, member_number = row
            reply_text = f"名前: {name}\n地域: {region}\nメールアドレス: {email}\n電話番号: {phone_number}\n会員番号: {member_number}"
        else:
            reply_text = "会員情報が登録されていません。先に会員証登録を行ってください。"

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
    else:
        reply_text = "「会員証登録」または「会員証表示」と送信してください。"
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )

# 会員登録フォームを表示する
@app.route('/register')
def register_form():
    user_id = request.args.get('user_id')
    return render_template('register.html', user_id=user_id)


# 会員登録API (WebブラウザからのPOSTリクエストを受け付ける)
@app.route("/register", methods=['POST'])
def register_member():
    """
    Webフォームから送信された会員情報を登録する
    """
    line_user_id = request.form['line_user_id']
    name = request.form['name']  # 追加：名前を取得
    region = request.form['region']  # 追加：地域を取得
    email = request.form.get('email', '')  # 任意項目：デフォルト値を設定
    phone_number = request.form.get('phone_number', '')  # 任意項目：デフォルト値を設定

    app.logger.info(
        f"Registering user: {line_user_id}, Name: {name}, Region: {region}, Email: {email}, Phone: {phone_number}")  # ログ出力

    db = get_db()
    cursor = db.cursor()
    try:
        # 既に登録されているか確認
        cursor.execute("SELECT * FROM members WHERE line_user_id = ?", (line_user_id,))
        existing_member = cursor.fetchone()

        if existing_member:
            # 更新処理
            cursor.execute(
                "UPDATE members SET name = ?, region = ?, email = ?, phone_number = ? WHERE line_user_id = ?",
                (name, region, email, phone_number, line_user_id)
            )
            db.commit()
            # HTMLを返すように修正
            return render_template('registration_complete.html', message='会員情報を更新しました。', user_id=line_user_id)
        else:
            # 新規登録処理
            # 最大の会員番号を取得して次の番号を割り振る
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
        return render_template('show_member_card.html', name=member[0], region=member[1], member_number=member[2])
    else:
        return "会員情報が見つかりません", 404


if __name__ == "__main__":
    # ポート番号を環境変数から取得するように変更 (Heroku対応)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
