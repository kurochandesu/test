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
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import logging
import random

# アプリ設定
app = Flask(__name__)
app.secret_key = 'your_secret_key_here' # flashメッセージのためにシークレットキーを設定

# ロギング設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 環境変数からLINE Botの設定情報を取得
# 本番環境では、環境変数に設定することを推奨
YOUR_CHANNEL_ACCESS_TOKEN = os.environ.get('YOUR_CHANNEL_ACCESS_TOKEN')
YOUR_CHANNEL_SECRET = os.environ.get('YOUR_CHANNEL_SECRET')

if YOUR_CHANNEL_ACCESS_TOKEN is None:
    print("環境変数YOUR_CHANNEL_ACCESS_TOKENが設定されていません。")
    YOUR_CHANNEL_ACCESS_TOKEN = "YOUR_CHANNEL_ACCESS_TOKEN" # デフォルト値を設定
if YOUR_CHANNEL_SECRET is None:
    print("環境変数YOUR_CHANNEL_SECRETが設定されていません。")
    YOUR_CHANNEL_SECRET = "YOUR_CHANNEL_SECRET" # デフォルト値を設定

line_bot_api = LineBotApi(YOUR_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(YOUR_CHANNEL_SECRET)

# データベース設定
DATABASE = 'members.db'

def get_db():
    """
    アプリケーションコンテキスト内でデータベース接続を管理する
    """
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row  # カラム名をキーとする辞書形式で取得できるようにする
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    """
    アプリケーションコンテキスト終了時にデータベース接続を閉じる
    """
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    """
    データベースを初期化する（テーブル作成など）
    schema.sql に依存せず、直接テーブルを作成するように変更
    """
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS members (
                line_user_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                region TEXT NOT NULL,
                email TEXT,
                phone_number TEXT,
                member_number TEXT NOT NULL UNIQUE
            )
        ''')
        db.commit()
        logger.info("Database initialized and members table created.")

# アプリケーション起動時にデータベースを初期化
# init_db() # コメントアウト。run.pyで初期化するように変更

# LINE Webhookルート
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
    line_user_id = event.source.user_id
    text = event.message.text

    logger.info(f"Received message from {line_user_id}: {text}")

    if text == "登録":
        # 登録フォームのURLを生成
        register_url = url_for('show_registration_form', user_id=line_user_id, _external=True)  # 絶対URLを生成
        reply_message = f"以下のURLから会員登録を行ってください。\n{register_url}"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_message))
    elif text == "会員証":
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT name, region, member_number FROM members WHERE line_user_id = ?", (line_user_id,))
        member = cursor.fetchone()
        if member:
            name = member['name']
            region = member['region']
            member_number = member['member_number']
            reply_message = f"名前: {name}\n地域: {region}\n会員番号: {member_number}"
        else:
            reply_message = "会員情報が登録されていません。登録してください。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_message))
    else:
        reply_message = "登録 または 会員証 と送信してください。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_message))

@app.route("/register_form/<user_id>")
def show_registration_form(user_id):
    """
    会員登録フォームを表示する
    """
    return render_template('register.html', user_id=user_id)

def generate_member_number():
    """
    重複しない会員番号を生成する関数 (例: M0001, M0002...)
    """
    db = get_db()
    cursor = db.cursor()
    while True:
        member_number = f"M{random.randint(1, 9999):04d}"  # 4桁のランダムな数字
        cursor.execute("SELECT * FROM members WHERE member_number = ?", (member_number,))
        if not cursor.fetchone():
            return member_number

@app.route("/register", methods=["POST"])
def register():
    """
    会員登録処理を行う
    """
    db = get_db()
    cursor = db.cursor()

    try:
        line_user_id = request.form["line_user_id"]
        name = request.form["name"]
        region = request.form["region"]
        email = request.form.get("email")  # 任意項目なので get() を使用
        phone_number = request.form.get("phone_number")  # 任意項目

        # 必須項目のバリデーション
        if not name or not region:
            raise ValueError("名前と地域は必須項目です。")

        # LINEユーザーIDの存在チェック
        cursor.execute("SELECT * FROM members WHERE line_user_id = ?", (line_user_id,))
        existing_member = cursor.fetchone()
        if existing_member:
            # 既に登録されている場合は更新として扱う
            member_number = existing_member['member_number'] # 既存の会員番号を使用
            cursor.execute(
                "UPDATE members SET name = ?, region = ?, email = ?, phone_number = ? WHERE line_user_id = ?",
                (name, region, email, phone_number, line_user_id)
            )
            db.commit()
            return render_template('registration_complete.html', message='会員情報を更新しました。', user_id=line_user_id)

        else:
            # メールアドレスの形式チェック (簡易的な例)
            if email and "@" not in email:
                raise ValueError("メールアドレスの形式が正しくありません。")

            # 電話番号の形式チェック (簡易的な例)
            if phone_number and not phone_number.isdigit():
                raise ValueError("電話番号の形式が正しくありません。")
            
            # 会員番号の重複チェックと生成
            member_number = generate_member_number()

            # 登録処理
            cursor.execute(
                "INSERT INTO members (line_user_id, name, region, email, phone_number, member_number) VALUES (?, ?, ?, ?, ?, ?)",
                (line_user_id, name, region, email, phone_number, member_number),
            )
            db.commit()
            return render_template('registration_complete.html', message='会員登録が完了しました。', user_id=line_user_id)

    except ValueError as ve:
        db.rollback()
        logger.error(f"Validation Error: {ve}")
        # flash(str(ve)) # HTMLテンプレートでメッセージを表示する場合はflashを使用
        return jsonify({'error': '入力エラー', 'message': str(ve)}), 400  # 400 Bad Request
    except Exception as e:
        db.rollback()
        logger.error(f"Error registering member: {e}")
        return jsonify({'error': '登録失敗', 'message': '会員登録に失敗しました。' + str(e)}), 500


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
        # 登録されていない場合は、登録フォームにリダイレクト
        return redirect(url_for('show_registration_form', user_id=user_id))

@app.route('/update_profile', methods=['GET', 'POST'])
def update_profile():
    """
    会員情報を更新する
    """
    db = get_db()
    cursor = db.cursor()
    user_id = request.args.get('user_id') # GETリクエストの場合はクエリパラメータから取得
    if request.method == 'POST':
        user_id = request.form.get('line_user_id') # POSTリクエストの場合はフォームデータから取得

    if user_id is None:
        # user_id がない場合はエラーハンドリング
        return jsonify({'error': 'エラー', 'message': 'LINEユーザーIDが指定されていません。'}), 400

    if request.method == 'POST':
        email = request.form.get('email')
        member_number = request.form.get('member_number')

        try:
            # バリデーション:  必要であれば、emailとmember_numberの形式チェックを行う
            if email and "@" not in email:
                raise ValueError("メールアドレスの形式が正しくありません。")
            # 会員番号の形式チェックは、generate_member_numberでMから始まる形式を生成しているので、
            # ユーザーが直接入力する更新フォームでは、Mから始まる形式を強制しない方が良いかもしれません。
            # もしMから始まる形式を強制する場合は、以下のコメントアウトを解除してください。
            # if member_number and not member_number.startswith("M"):
            #     raise ValueError("会員番号の形式が正しくありません。")

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
            # 登録を促すページを表示する代わりに、登録フォームにリダイレクト
            return redirect(url_for('show_registration_form', user_id=user_id))

if __name__ == "__main__":
    # データベース初期化を行う
    with app.app_context():
        init_db()
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
