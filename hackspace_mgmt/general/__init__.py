from datetime import datetime, timezone, timedelta
from flask import Blueprint, current_app, flash, redirect, render_template, session, url_for, request, g
from flask_wtf import FlaskForm
import jwt
from markupsafe import Markup
import requests
from sqlalchemy.exc import NoResultFound
import secrets
from wtforms import fields, widgets
from wtforms.validators import EqualTo, DataRequired
import yarl

import logging

from hackspace_mgmt.models import db, Card, Member, Quiz, Machine, Induction, LegacyMachineAuth
from hackspace_mgmt.forms import SerialField

from . import quiz
from . import label
from . import profile
from . import induction
from .helpers import login_required

bp = Blueprint("general", __name__)

logger = logging.Logger(__name__)


class CardLoginForm(FlaskForm):
    serial_number = SerialField(
        'Remove card/fob from wallet (if applicable) and scan on reader above',
        widget=widgets.HiddenInput(),
        suppress_enter=False,
        # render_kw={"autofocus": "1", "autocomplete": "off"},
        render_kw={"autocomplete": "off"},
        description="Removing from wallet is required to avoid accidentally scanning the wrong card"
    )

    submit_label = "Login"

@bp.route("/", methods=("GET", "POST"))
@login_required
def index():
    return render_template("index.html", is_kiosk=is_kiosk())

@bp.route("/login/jwt", methods=("GET", "POST"))
def login_jwt():
    try_jwt = request.args.get('tryJwt')
    jwt_token = request.args.get('jwt') 
    jwt_public_key_file = current_app.config["JWT_LOGIN_PUBLIC_KEY_FILE"]
    jwt_start_url = current_app.config["JWT_LOGIN_START_URL"]
    jwt_audience = current_app.config["JWT_LOGIN_AUDIENCE"]

        
    if is_kiosk():
        return redirect(url_for("general.login"))        

    if try_jwt is not None and try_jwt != "":
        return redirect(jwt_start_url)

    if jwt_token is not None and jwt_token != "":
        with open(jwt_public_key_file) as kf:
            jwt_public_key = kf.read()
            decoded = jwt.decode(jwt_token, jwt_public_key, audience=jwt_audience, algorithms="RS256")
            member = db.session.get(Member, decoded['sub'])

            if member is not None and member.id == int(decoded['sub']) :
                session['logged_in_member'] = member.id
                session['sid'] = secrets.token_urlsafe()
                return redirect(url_for("general.index"))
            else :
                print(member, int(decoded['sub']))

    return render_template("login_jwt.html", jwt_start_url=jwt_start_url)

@bp.route("/login", methods=("GET", "POST"))
def login():
    login_form = CardLoginForm(request.form, meta={'csrf': False})

    if not is_kiosk():
        return redirect(url_for("general.login_jwt"))

    if login_form.validate_on_submit():
        card_serial = login_form.serial_number.data

        card_select = db.select(Card).where(Card.card_serial==card_serial and Card.verified==True)
        card_select = card_select.join(Card.member)
        try:
            card = db.session.execute(card_select).scalar_one()
            if card.member is not None:
                session["logged_in_member"] = card.member.id
                session["sid"] = secrets.token_urlsafe()
            else:
                flash("Card not yet registered to a member")
            return redirect(url_for("general.index"))
        except NoResultFound:
            session["scanned_card_serial"] = card_serial
            return redirect(url_for("general.enroll_card_number"))

    return render_template("login.html", login_form=login_form)


@bp.route("/logout")
def logout():
    try:
        storage_logout_url = current_app.config["STORAGE_APP_URL"] + "/backchannel-logout"
        login_secret = current_app.config["STORAGE_LOGIN_SECRET"]

        now = datetime.now(timezone.utc)
        exp = now + timedelta(seconds=60)

        logout_token = {
            "sid": session["sid"],
            "exp": int(exp.timestamp()),
            "events": {
                "http://schemas.openid.net/event/backchannel-logout": {}
            }
        }

        logout_token = jwt.encode(logout_token, login_secret, algorithm="HS256")

        payload = {
            "logout_token": logout_token
        }

        req = requests.post(storage_logout_url, data=payload)
    except Exception as ex:
        logger.warning("Error sending logout request to storage", ex)

    session.clear()
    flash("Logged out successfully")
    return redirect(url_for("general.login"))

class CardInfoForm(FlaskForm):
    number_on_front = fields.IntegerField(
        'Number on front of card/keyfob',
        validators=[DataRequired()],
        render_kw={"autocomplete": "off"}
    )
    number_on_front_verify = fields.IntegerField(
        'Confirm number on front of card/keyfob',
        validators=[EqualTo("number_on_front", "Values do not match")],
        render_kw={"autocomplete": "off"}
    )

    submit_label = "Next"

    def __init__(self, formdata=None, obj=None, prefix='', **kwargs):
        super().__init__(formdata=formdata, obj=obj, prefix=prefix, **kwargs)

        keycard_url = url_for("static", filename="images/keycards.jpg")
        keycard_help = "If this number is worn out then ask a committee member and we'll look it up for you."
        self.number_on_front_verify.description = Markup(
            f"<img src='{keycard_url}' /> {keycard_help}"
        )
        self.card = None

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators=extra_validators):
            return False

        number_on_front = self.number_on_front.data

        card_select = db.select(Card).where(Card.number_on_front==number_on_front)
        card_select = card_select.join(Card.member)
        try:
            card = db.session.execute(card_select).scalar_one()
        except NoResultFound:
            card = None

        if (card is None or card.member is None):
            self.number_on_front.errors.append("Card number not recognised")
            return False

        card.unverified_serial = session["scanned_card_serial"]
        db.session.commit()

        if card.card_serial:
            self.number_on_front.errors.append(
                "This card number has already been enrolled. " +
                "If you had previously scanned the wrong card then message the committee and we'll update it."
            )
            return False

        self.card = card
        return True

@bp.route("/enroll/card_number", methods=("GET", "POST"))
def enroll_card_number():
    if "scanned_card_serial" not in session:
        return redirect(url_for("general.login"))

    enroll_form = CardInfoForm(request.form)
    logger.info("got request", request)
    if enroll_form.validate_on_submit():
        session["unverified_card_id"] = enroll_form.card.id
        session["unverified_member_id"] = enroll_form.card.member.id
        return redirect(url_for("general.enroll_personal"))

    return render_template("enroll_card.html", enroll_form=enroll_form)


class EmailForm(FlaskForm):
    email = fields.EmailField(
        "Email you signed up with",
        validators=[DataRequired()],
        render_kw={"autocomplete": "off"},
        description="If you have forgotten then ask a committee member and we'll look it up for you."
    )

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators=extra_validators):
            return False

        unverified_member_id = session.get("unverified_member_id")
        member = db.session.get(Member, unverified_member_id)

        if self.email.data not in [member.email, member.alt_email]:
            self.email.errors.append("Incorrect email for card")
            return False

        return True


@bp.route("/enroll/personal", methods=("GET", "POST"))
def enroll_personal():
    if "unverified_member_id" not in session:
        return redirect(url_for("general.login"))

    enroll_form = EmailForm(request.form)
    if enroll_form.validate_on_submit():
        card_id = session["unverified_card_id"]
        card = db.session.get(Card, card_id)
        card.card_serial = card.unverified_serial
        card.unverified_serial = None
        db.session.commit()
        session["logged_in_member"] = session["unverified_member_id"]
        session["sid"] = secrets.token_urlsafe()
        flash("Card enrolled successfully")
        return redirect(url_for("general.index"))

    return render_template("enroll_personal.html", enroll_form=enroll_form)


@bp.route("/storage-login")
@login_required
def storage_login():
    login_secret = current_app.config["STORAGE_LOGIN_SECRET"]
    name = str(g.member)
    sub = f"member_{g.member.id}"
    email = g.member.email

    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=60)

    payload = {
        "sub": sub,
        "name": name,
        "email": email,
        "exp": int(exp.timestamp()),
        "sid": session["sid"],
        "nonce": secrets.token_urlsafe()
    }

    encoded = jwt.encode(payload, login_secret, algorithm="HS256")
    redirect_url = yarl.URL(current_app.config["STORAGE_APP_URL"])
    redirect_url = redirect_url.update_query(login_token=encoded)
    return redirect(redirect_url)

def is_kiosk():
    kiosk_token = current_app.config["KIOSK_TOKEN"]
    user_agent = request.headers.get('User-Agent')

    if kiosk_token in user_agent:
        return True
    else:
        return False
    
def init_app(app):
    app.register_blueprint(bp)
    app.register_blueprint(quiz.bp)
    app.register_blueprint(label.bp)
    app.register_blueprint(profile.bp)
    app.register_blueprint(induction.bp)
