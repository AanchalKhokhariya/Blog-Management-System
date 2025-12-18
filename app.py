from flask import Flask, render_template, request, session, url_for, redirect
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import random
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv
import os
from werkzeug.utils import secure_filename

UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


load_dotenv()

app = Flask(__name__)
app.secret_key = "supersecretkey"

app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://postgres:2807@localhost/user_blog"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

app.config['MAIL_SERVER'] = os.getenv("MAIL_SERVER")
app.config['MAIL_PORT'] = int(os.getenv("MAIL_PORT"))
app.config['MAIL_USE_TLS'] = os.getenv("MAIL_USE_TLS") == "True"
app.config['MAIL_USERNAME'] = os.getenv("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.getenv("MAIL_PASSWORD")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

db = SQLAlchemy(app)


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    gmail = db.Column(db.String(200), nullable=False, unique=True)
    password = db.Column(db.Text, nullable=False)
    posts = db.relationship("Post", backref="author", lazy=True)
    comments = db.relationship("Comment", backref="author", lazy=True)
    followers = db.relationship("Follow", foreign_keys="Follow.following_id",backref="following",lazy=True)
    following = db.relationship("Follow", foreign_keys="Follow.follower_id", backref="follower", lazy=True)

class Post(db.Model):
    __tablename__ = "posts"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    comments = db.relationship("Comment", backref="post", lazy=True, cascade="all, delete")
    likes = db.relationship("Like", backref="post", lazy=True, cascade="all, delete")


class Comment(db.Model):
    __tablename__ = "comments"
    id = db.Column(db.Integer, primary_key=True)
    comment = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

class Like(db.Model):
    __tablename__ = "likes"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False)


class Follow(db.Model):
    __tablename__ = "follows"
    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    following_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

with app.app_context():
    db.create_all()

@app.context_processor
def user_name():
    if "name" in session:
        return {"name": session["name"]}
    return {"name": ""}


@app.route("/")
def home():
    return render_template("main.html", page="first_page", is_logged_in=("user_id" in session))


@app.route("/register")
def show_register():
    return render_template("main.html", page="register", is_logged_in="user_id" in session)


@app.route("/register", methods=["POST"])
def register():
    name = request.form.get("name")
    gmail = request.form.get("gmail")
    password = request.form.get("password")
    confirm = request.form.get("confirm")

    if password != confirm:
        return render_template("main.html", page="register", error="Passwords do not match")
    
    if User.query.filter((User.name == name) | (User.gmail == gmail)).first():
        return render_template("main.html", page="register", error="User already exists!")

    if User.query.filter(User.name == name).first():
        return render_template("main.html", page="register", error="Username already exists!")
    
    if User.query.filter(User.gmail == gmail).first():
        return render_template("main.html", page="register", error="User with this Gmail already exists!")

    otp = str(random.randint(100000, 999999))
    session.update({
        "otp": otp,
        "temp_name": name,
        "temp_gmail": gmail,
        "temp_password": password,
    })

    send_otp_email(gmail, otp)

    return render_template("main.html", page="verify_otp")

    
@app.route("/verify_otp", methods=["POST"])
def verify_otp():
    input_otp = request.form.get("otp")

    if input_otp != session.get("otp"):
        return render_template("main.html", page="verify_otp", error="Invalid OTP! Try again.")

    new_user = User(
        name=session["temp_name"],
        gmail=session["temp_gmail"],
        password=generate_password_hash(session["temp_password"]),
    )

    db.session.add(new_user)
    db.session.commit()

    for key in ["otp", "temp_name", "temp_gmail", "temp_password"]:
        session.pop(key, None)

    return redirect(url_for("login"))

def send_otp_email(receiver, otp):
    sender = app.config["MAIL_USERNAME"]
    password = app.config["MAIL_PASSWORD"]

    msg = MIMEText(f"Your OTP for registration is: {otp}")
    msg["Subject"] = "Your OTP Verification Code"
    msg["From"] = sender
    msg["To"] = receiver

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, receiver, msg.as_string())
        return True
    except Exception as e:
        print("Email Error:", e)
        return False


@app.route("/login")
def show_login():
    if "user_id" in session:
        return redirect(url_for("home"))  
    return render_template("main.html", page="login")


@app.route("/login", methods=["POST"])
def login():
    if "user_id" in session:
        return render_template("main.html", page="home", error="User is already logged-in", is_logged_in=True)

    gmail = request.form.get("gmail")
    password = request.form.get("password")

    user = User.query.filter_by(gmail=gmail).first()

    if user and check_password_hash(user.password, password):
        session["user_id"] = user.id
        session["gmail"] = user.gmail
        session["name"] = user.name

        return redirect(url_for("screen"))

    return render_template("main.html", page="login", error="Invalid email or password")


@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "GET":
        return render_template("main.html", page="forgot_password")

    gmail = request.form.get("gmail")
    user = User.query.filter_by(gmail=gmail).first()

    if not user:
        return render_template("main.html", page="forgot_password", error="Email not registered")

    otp = str(random.randint(100000, 999999))
    session["fp_otp"] = otp
    session["fp_gmail"] = gmail

    send_otp_email(gmail, otp)

    return render_template("main.html", page="verify_fp_otp")


@app.route("/verify_fp_otp", methods=["POST"])
def verify_fp_otp():
    input_otp = request.form.get("otp")

    if input_otp != session.get("fp_otp"):
        return render_template("main.html", page="verify_fp_otp", error="Invalid OTP")

    return render_template("main.html", page="reset_password")


@app.route("/reset_password", methods=["POST"])
def reset_password():
    password = request.form.get("password")
    confirm = request.form.get("confirm")

    if password != confirm:
        return render_template("main.html", page="reset_password", error="Passwords do not match")

    user = User.query.filter_by(gmail=session.get("fp_gmail")).first()
    if not user:
        return redirect(url_for("login"))

    user.password = generate_password_hash(password)
    db.session.commit()

    return redirect(url_for("login"))

@app.route("/screen")
def screen():
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    return render_template("main.html", page="screen", is_logged_in=True)


@app.route("/profile")
def profile():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = db.session.get(User, session["user_id"])

    posts = Post.query.filter_by(user_id=user.id)\
                  .order_by(Post.created_at.desc())\
                  .all()

    followers = Follow.query.filter_by(follower_id=user.id).count()
    following = Follow.query.filter_by(following_id=user.id).count()

    return render_template("main.html", page="profile", user=user, posts=posts, followers=followers, following=following)
    

@app.route("/add_blog", methods=["GET", "POST"])
def add_blog():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "GET":
        return render_template("main.html", page="add_blog")

    title = request.form.get("title")
    content = request.form.get("content")
    image_url = request.form.get("image_url")
    image_file = request.files.get("image_file")

    if not title or not content:
        return render_template("main.html", page="add_blog", error="Title and content are required")

    image_path = None

    if image_file and image_file.filename != "":
        filename = secure_filename(image_file.filename)
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        image_file.save(save_path)

        image_path = f"/static/uploads/{filename}"

    elif image_url:
        image_path = image_url

    new_blog = Post(
        title=title,
        content=content,
        image=image_path,
        created_at=datetime.now(),
        user_id=session["user_id"]
    )

    db.session.add(new_blog)
    db.session.commit()

    return redirect(url_for("profile"))

@app.route("/comment/<int:post_id>", methods=["POST"])
def add_comment(post_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    text = request.form.get("comment")

    if text:
        new_comment = Comment(
            comment=text,
            user_id=session["user_id"],
            post_id=post_id
        )
        db.session.add(new_comment)
        db.session.commit()

    return redirect(url_for("profile"))


@app.route("/like/<int:post_id>", methods=["POST"])
def like_post(post_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    existing_like = Like.query.filter_by(
        user_id=session["user_id"],
        post_id=post_id
    ).first()

    if existing_like:
        db.session.delete(existing_like)  # Unlike
    else:
        new_like = Like(
            user_id=session["user_id"],
            post_id=post_id
        )
        db.session.add(new_like)

    db.session.commit()
    return redirect(url_for("profile"))



# @app.route("/profile")
# def profile():
#     if "user_id" not in session:
#         return redirect(url_for("login"))
    
#     user = db.session.get(User, session["user_id"])
#     posts = Post.query.filter_by(user_id=user.id).all()
#     followers = Follow.query.filter_by(follower_id=user.id).count()
#     following = Follow.query.filter_by(following_id=user.id).count()
    
#     return render_template("main.html", user=user, posts=posts, followers=followers, following=following)


# @app.route("/add_blogs")
# def add_blog():
#     if "user_id" not in session:
#         return redirect(url_for("login"))
    
#     title = request.form.get("title")
#     content = request.form.get("content")
#     image = request.form.get("image")

#     new_blog = Post(
#         title = title,
#         content = content,
#         image = image
#     )

#     db.session.add(new_blog)
#     db.session.commit()

#     return redirect("/profile")


# @app.route("/comment", methods=["POST"])
# def comment():
#     if "user_id" not in session:
#         return redirect(url_for("login"))

#     post_id = request.form.get("post_id")
#     text = request.form.get("comment")

#     new_comment = Comment(
#         comment=text,
#         post_id=post_id,
#         user_id=session["user_id"]
#     )

#     db.session.add(new_comment)
#     db.session.commit()

#     return redirect(request.referrer)


# @app.route("/like/<int:post_id>")
# def like_post(post_id):
#     if "user_id" not in session:
#         return redirect(url_for("login"))

#     existing = Like.query.filter_by(user_id=session["user_id"], post_id=post_id).first()

#     if existing:
#         db.session.delete(existing)
#     else:
#         db.session.add(Like(user_id=session["user_id"], post_id=post_id))

#     db.session.commit()
#     return redirect(request.referrer)


# @app.route("/follow/<int:user_id>")
# def follow_user(user_id):
#     if "user_id" not in session or session["user_id"] == user_id:
#         return redirect(request.referrer)

#     existing = Follow.query.filter_by(follower_id=session["user_id"],following_id=user_id).first()

#     if existing:
#         db.session.delete(existing)
#     else:
#         db.session.add(Follow(
#             follower_id=session["user_id"],
#             following_id=user_id
#         ))

#     db.session.commit()
#     return redirect(request.referrer)

    
@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)

