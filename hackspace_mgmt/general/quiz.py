from flask import Blueprint, flash, redirect, render_template, url_for, request, g, session
from flask_wtf import FlaskForm
from markupsafe import Markup, escape
from wtforms import fields, widgets, ValidationError
from wtforms.validators import InputRequired
from sqlalchemy.dialects.postgresql import insert
import yaml
import logging
import re
from datetime import datetime, timezone

from hackspace_mgmt.models import Machine, QuizCompletion, db, Quiz, Member, Induction, LegacyMachineAuth
from hackspace_mgmt.general.helpers import login_required
from hackspace_mgmt.audit import create_audit_log

bp = Blueprint("quiz", __name__)

logger = logging.Logger(__name__)

class Exactly:
    def __init__(self, value, message=None):
            self.value = value
            self.message = message

    def __call__(self, form, field):
        if isinstance(self.value, set) and set(field.data) == self.value:
            return
        elif field.data == self.value:
            return
        message = self.message
        if message is None:
            message = "Incorrect answer"
        raise ValidationError(message)

class MultiCheckboxField(fields.SelectMultipleField):
    """
    A multiple-select, except displays a list of checkboxes.

    Iterating the field will produce subfields, allowing custom rendering of
    the enclosed checkbox fields.
    """
    widget = widgets.ListWidget(prefix_label=False)
    option_widget = widgets.CheckboxInput()


LINK_MD_REGEX = re.compile(r"\[\[(?P<url>[^|]+)\|(?P<text>[^\]]+)\]\]")
IMAGE_MD_REGEX = re.compile(r"\{\{(?P<link>[^}]+)\}\}")

WIKI_MEDIA_URL = "https://wiki.bristolhackspace.org/_media/"


def md_parse(text: str):
    def make_url(match):
        text = escape(match.group("text"))
        url = match.group("url")
        return f"<a href='{url}' target='_blank' rel='noopener noreferrer'>{text}</a>"
    text = LINK_MD_REGEX.sub(make_url, text)

    def make_img(match):
        link = match.group("link")
        attrs = []
        parts = link.split("?", maxsplit=1)
        if len(parts)==2:
            link = parts[0]
            try:
                width = int(parts[1])
                attrs.append(f"width='{width}rem'")
            except ValueError:
                pass

        wikipath = link.split(":")
        if wikipath[0] == "wiki":
            url = WIKI_MEDIA_URL + "/".join(wikipath[1:])
        else:
            url = url_for("static", filename=link)
        attrs.append(f"src='{url}'")

        attrs = " ".join(attrs)
        return f"<img {attrs}/>"
    text = IMAGE_MD_REGEX.sub(make_img, text)
    return Markup(text)

@bp.route("/quiz/<int:quiz_id>/intro", methods=("GET", "POST"))
@login_required
def intro(quiz_id):
    machine_id = request.args.get("machine_id")
    if machine_id is not None:
        return_url = url_for("induction.machine", machine_id=machine_id)
    else:
        return_url = url_for("general.index")

    quiz = db.get_or_404(Quiz, quiz_id)

    quiz_data = yaml.load(quiz.questions, Loader=yaml.CLoader)
    question_keys = list(quiz_data.keys())
    first_question_url = url_for("quiz.question", quiz_id=quiz_id, key=question_keys[0], machine_id=machine_id)

    intro_text = md_parse(quiz.intro)

    return render_template("quiz_intro.html", intro_text=intro_text, quiz_title=quiz.title, return_url=return_url, first_key=question_keys[0], first_question_url=first_question_url)


@bp.route("/quiz/<int:quiz_id>/question/<string:key>", methods=("GET", "POST"))
@login_required
def question(quiz_id, key):

    machine_id = request.args.get("machine_id")
    if machine_id is not None:
        return_url = url_for("induction.machine", machine_id=machine_id)
    else:
        return_url = url_for("general.index")

    if "quizzes" not in session :
        session["quizzes"] = { }

    if (str(quiz_id)) not in session["quizzes"] :
        session["quizzes"][str(quiz_id)] = { }

    quiz = db.get_or_404(Quiz, quiz_id)

    quiz_data = yaml.load(quiz.questions, Loader=yaml.CLoader)

    class QuizForm(FlaskForm):
        submit_label = "Submit"

    question_keys = list(quiz_data.keys())
    question = quiz_data[key]
    current = question_keys.index(key)
    questions_total = len(question_keys)

    if question is None:
        return redirect(return_url)

    set_quiz_attr(QuizForm, question, key) 

    quiz_form = QuizForm(request.form, quiz_data=quiz_data)

    now=datetime.now(timezone.utc)

    if quiz_form.validate_on_submit():

        # `validate_on_submit` checks correct / incorrect, answers stored to check all questions at the end
        session["quizzes"][str(quiz_id)][key] = question["correct_answers"] if "correct_answers" in  question else question["correct_answer"]
        session.modified = True


        if current + 1 >= len(question_keys) :
            missed = None
            for key in question_keys:

                if key not in  session["quizzes"][str(quiz_id)] :
                    missed = key
                    break

                session_value = session["quizzes"][str(quiz_id)][key] 
                question_value = quiz_data[key]['correct_answers'] if "correct_answers" in quiz_data[key] else quiz_data[key]['correct_answer']

                if session_value is None or question_value != session_value :
                    missed = key 

            if missed is None :
                complete_quiz(quiz, quiz_data, g.member) 
                correct_message_text = correct_message(quiz, machine_id, g.member)

                session["quizzes"][str(quiz_id)] = {}
                session.modified = True

                flash(correct_message_text)
                return redirect(return_url)
            else :
                return redirect(url_for("quiz.question", quiz_id=quiz_id, key=missed, machine_id=machine_id))
        else :
            next_key = question_keys[current + 1]
            return redirect(url_for("quiz.question", quiz_id=quiz_id, key=next_key, machine_id=machine_id ))

    elif request.method == "POST":
        create_audit_log(
            "question",
            "fail",
            data={
                "question": question,
                "quiz_id": quiz.id
            },
            member=g.member,
            logged_at=now
        )

    intro_text = md_parse(quiz.intro)

    return render_template("quiz_question.html", intro_text=intro_text, quiz_form=quiz_form, quiz_title=quiz.title, return_url=return_url, current=current, questions_total=questions_total)

@bp.route("/quiz/<int:quiz_id>", methods=("GET", "POST"))
@login_required
def index(quiz_id):

    machine_id = request.args.get("machine_id")
    if machine_id is not None:
        return_url = url_for("induction.machine", machine_id=machine_id)
    else:
        return_url = url_for("general.index")

    quiz = db.get_or_404(Quiz, quiz_id)

    quiz_data = yaml.load(quiz.questions, Loader=yaml.CLoader)

    first = next(iter(quiz_data))

    if "multi_page" in quiz_data[first] and quiz_data[first]["multi_page"] :
        return redirect(url_for("quiz.intro", quiz_id=quiz_id, machine_id=machine_id))

    class QuizForm(FlaskForm):
        submit_label = "Submit"

    for key, question in quiz_data.items():
        set_quiz_attr(QuizForm, question, key) 

    quiz_form = QuizForm(request.form, quiz_data=quiz_data)

    now=datetime.now(timezone.utc)

    if quiz_form.validate_on_submit(): 

        complete_quiz(quiz, quiz_data, g.member)

        correct_msg = correct_message(quiz, machine_id, g.member)
        flash(correct_msg)
        return redirect(return_url)
    elif request.method == "POST":
        create_audit_log(
            "quiz",
            "fail",
            data={
                "questions": quiz_data,
                "quiz_id": quiz.id
            },
            member=g.member,
            logged_at=now
        )

    intro_text = md_parse(quiz.intro)

    return render_template("quiz.html", intro_text=intro_text, quiz_form=quiz_form, quiz_title=quiz.title, return_url=return_url)

def set_quiz_attr(quizForm, question, key):
    qtype = question["type"]
    label = md_parse(question["label"])
    if qtype == "pick_one":
        choices = list((k, md_parse(v)) for k,v in question["answers"].items())
        answer_validator = Exactly(question["correct_answer"], question.get("incorrect_hint"))
        field = fields.RadioField(label, choices=choices, validators=[InputRequired(), answer_validator])
    elif qtype == "select_all":
        number_of_answers = len(set(question["correct_answers"]))
        answer_validator = Exactly(set(question["correct_answers"]), question.get("incorrect_hint") + f" (choose {number_of_answers} answers)")
        choices = list((k, md_parse(v)) for k,v in question["answers"].items())
        field = MultiCheckboxField(label, choices=choices, validators=[answer_validator])
    elif qtype == "yes_no":
        answer_validator = Exactly(question["correct_answer"], question.get("incorrect_hint"))
        field = fields.BooleanField(label, validators=[answer_validator])
    elif qtype == "textbox":
        answer_validator = Exactly(question["correct_answer"], question.get("incorrect_hint"))
        field = fields.StringField(
            label,
            validators=[InputRequired(), answer_validator],
            render_kw={"autocomplete": "off"},
        )

    setattr(quizForm, key, field)

def complete_quiz(quiz, quiz_data, member):
    now=datetime.now(timezone.utc)
    upsert_stmt = insert(QuizCompletion).values(
        member_id=g.member.id,
        quiz_id=quiz.id,
        completed_on=now
    ).on_conflict_do_update(
        index_elements=[QuizCompletion.quiz_id, QuizCompletion.member_id],
        set_=dict(
            completed_on=now
        ),
    )
    db.session.execute(upsert_stmt)

    create_audit_log(
        "quiz",
        "pass",
        data={
            "questions": quiz_data,
            "quiz_id": quiz.id
        },
        member=g.member,
        logged_at=now,
        commit=False
    )
    db.session.commit()

def correct_message(quiz, machine_id, member):
    correct_msg = f"All correct! "

    machine = None
    if machine_id is not None:
        machine = db.session.get(Machine, machine_id)
    if machine:
        if machine.is_member_inducted(g.member):
            if machine.legacy_auth == LegacyMachineAuth.padlock:
                correct_msg += f"The padlock code for the {machine.name} is {machine.legacy_password}."
            elif machine.legacy_auth == LegacyMachineAuth.password:
                correct_msg += f"The password for the {machine.name} is \"{machine.legacy_password}\"."
            else:
                correct_msg += f"You should now be able to use the {machine.name}."
        else:
            correct_msg += "You'll need to complete further training first however."

    return correct_msg
