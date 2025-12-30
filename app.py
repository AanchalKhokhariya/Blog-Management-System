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
    bio = db.Column(db.String(200), nullable=True, default='')
    password = db.Column(db.Text, nullable=False)
    profile_pic = db.Column(db.String(300)) 
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


@app.route("/")
def home():
    if "user_id" not in session:
        posts = Post.query.order_by(Post.created_at.desc()).all()
        return render_template("main.html", page="home", posts=posts, user=None, is_logged_in=False)

    current_user_id = session["user_id"]

    posts = (Post.query.filter(Post.user_id != current_user_id).order_by(Post.created_at.desc()).all())

    following_ids = {
        f.following_id
        for f in Follow.query.filter_by(follower_id=current_user_id).all()
    }

    return render_template("main.html", page="screen", posts=posts, following_ids=following_ids, is_logged_in=True)


@app.route("/register")
def show_register():
    if "user_id" in session:
        return redirect(url_for("home"))  
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


@app.route("/resend_otp")
def resend_otp():
    
    if "temp_gmail" not in session:
        return redirect(url_for("register"))

    otp = str(random.randint(100000, 999999))
    session["otp"] = otp

    send_otp_email(session["temp_gmail"], otp)

    return render_template("main.html", page="verify_otp", message="A new OTP has been sent to your email.")


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

        return redirect(url_for("home"))

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


@app.route("/resend_fp_otp")
def resend_fp_otp():
    
    if "fp_gmail" not in session:
        return redirect(url_for("login"))

    otp = str(random.randint(100000, 999999))
    session["fp_otp"] = otp

    send_otp_email(session["fp_gmail"], otp)

    return render_template("main.html", page="verify_fp_otp", message="A new OTP has been sent to your email.")


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


@app.route("/profile")
def profile():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = db.session.get(User, session["user_id"])
    bio = request.form.get("bio")

    if not user:
        session.clear()
        return redirect(url_for("login"))

    posts = Post.query.filter_by(user_id=user.id).order_by(Post.created_at.desc()).all()

    followers = Follow.query.filter_by(following_id=user.id).count()
    following = Follow.query.filter_by(follower_id=user.id).count()

    is_following = Follow.query.filter_by(follower_id=session["user_id"], following_id=user.id).first() is not None

    return render_template("main.html",page="profile",user=user,bio=bio,posts=posts,followers=followers,following=following,is_following=is_following)


@app.route("/edit_profile")
def edit_profile():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = db.session.get(User, session["user_id"])
    
    followers = Follow.query.filter_by(follower_id=user.id).count()
    following = Follow.query.filter_by(following_id=user.id).count()

    return render_template("main.html",page="edit_profile",user=user, followers=followers, following=following)


@app.route("/update_profile", methods=["POST"])
def update_profile():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = db.session.get(User, session["user_id"])
    bio = request.form.get("bio")
    if bio is not None:  
        user.bio = bio

    file = request.files.get("profile_pic")
    if file and file.filename:
        filename = secure_filename(file.filename)
        path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(path)
        user.profile_pic = f"/static/uploads/{filename}"

    db.session.commit()
    return redirect(url_for("profile"))


@app.route("/delete_blog/<int:blog_id>", methods=["POST"])
def delete_blog(blog_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    blog = Post.query.get_or_404(blog_id)

    if blog.user_id != session["user_id"]:
        return "Unauthorized", 403

    db.session.delete(blog)
    db.session.commit()

    return redirect(url_for("profile"))


@app.route("/follow/<int:user_id>", methods=["POST"])
def follow_user(user_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    if session["user_id"] == user_id:
        return redirect(request.referrer)

    existing = Follow.query.filter_by(follower_id=session["user_id"],following_id=user_id).first()

    if existing:
        db.session.delete(existing)  
    else:
        db.session.add(Follow(follower_id=session["user_id"],following_id=user_id))

    db.session.commit()
    return redirect(request.referrer)


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


@app.route("/edit_blog/<int:blog_id>", methods=["GET"])
def edit_blog(blog_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    blog = Post.query.get_or_404(blog_id)

    if blog.user_id != session["user_id"]:
        return "Unauthorized", 403

    return render_template("main.html", page="edit_blog", blog=blog)


@app.route("/update_blog/<int:blog_id>", methods=["POST"])
def update_blog(blog_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    blog = Post.query.get_or_404(blog_id)

    if blog.user_id != session["user_id"]:
        return "Unauthorized", 403

    title = request.form.get("title")
    content = request.form.get("content")
    image_url = request.form.get("image_url")
    image_file = request.files.get("image_file")

    if not title or not content:
        return render_template("main.html",page="edit_blog",blog=blog,error="Title and content are required")

    blog.title = title
    blog.content = content

    if image_file and image_file.filename:
        filename = secure_filename(image_file.filename)
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        image_file.save(save_path)
        blog.image = f"/static/uploads/{filename}"

    elif image_url:
        blog.image = image_url

    db.session.commit()
    return redirect(url_for("profile"))


@app.route("/blog/<int:post_id>")
def blog_detail(post_id):
    post = Post.query.get_or_404(post_id)

    return render_template("main.html", page="blog_detail", post=post, is_logged_in=("user_id" in session))


@app.route("/comment/<int:post_id>", methods=["POST"])
def add_comment(post_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    comment_text = request.form.get("comment")
    

    if not comment_text or not comment_text.strip():
        return redirect(request.referrer)
    comment = Comment(comment=comment_text.strip(), post_id=post_id, user_id=session["user_id"])
    timestamp=datetime.now()
    db.session.add(comment,timestamp)
    db.session.commit()

    return redirect(request.referrer)



@app.route("/delete_comment/<int:comment_id>", methods=["POST"])
def delete_comment(comment_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    comment = Comment.query.get_or_404(comment_id)

    if comment.user_id != session["user_id"]:
        return "Unauthorized", 403

    db.session.delete(comment)
    db.session.commit()

    return redirect(url_for("home"))


@app.route("/edit_comment/<int:comment_id>", methods=["GET"])
def edit_comment(comment_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    comment = Comment.query.get_or_404(comment_id)

    if comment.user_id != session["user_id"]:
        return "Unauthorized", 403

    return render_template("main.html", page="edit_comment", comment=comment)


@app.route("/update_comment/<int:comment_id>", methods=["POST"])
def update_comment(comment_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    comment = db.session.get(Comment, comment_id)
    if not comment:
        return "Comment not found", 404

    if comment.user_id != session["user_id"]:
        return "Unauthorized", 403

    new_text = request.form.get("comment")
    comment.comment = new_text

    db.session.commit()
    return redirect(url_for("home"))  


@app.route("/like/<int:post_id>")
def like_post(post_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    existing = Like.query.filter_by(user_id=session["user_id"],post_id=post_id).first()

    if existing:
        db.session.delete(existing)
    else:
        db.session.add(Like(user_id=session["user_id"], post_id=post_id))

    db.session.commit()
    return redirect(request.referrer)

    
@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)
