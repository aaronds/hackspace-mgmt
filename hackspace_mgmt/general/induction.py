from flask import Blueprint, flash, redirect, render_template, url_for, request, g
from flask_wtf import FlaskForm
from wtforms import fields, widgets, ValidationError, validators
from datetime import datetime, timezone

import logging

from hackspace_mgmt.models import db, Machine, Induction, LegacyMachineAuth, Member
from hackspace_mgmt.general.helpers import login_required
from hackspace_mgmt.audit import create_audit_log

from sqlalchemy.dialects.postgresql import insert

bp = Blueprint("induction", __name__)

logger = logging.Logger(__name__)

@bp.route("/induction")
@login_required
def index():
    machine_select = db.select(Machine).where(Machine.hide_from_home == False).order_by(Machine.name)
    machines = db.session.scalars(machine_select).all()

    return render_template("induction.html", machines=machines, LegacyMachineAuth=LegacyMachineAuth)

@bp.route("/induction/<int:machine_id>")
@login_required
def machine(machine_id):
    machine = db.get_or_404(Machine, machine_id)

    member: Member = g.member

    completed_quizes = {completion.quiz:completion for completion in member.quiz_completions if not completion.has_expired()}
    expired_quizes = set(completion.quiz for completion in member.quiz_completions if completion.has_expired())

    induction = None
    for member_induction in member.inductions:
        if member_induction.machine == machine:
            induction = member_induction
            break

    return render_template(
        "machine_induction.html",
        machine=machine,
        completed_quizes=completed_quizes,
        expired_quizes=expired_quizes,
        induction=induction,
        LegacyMachineAuth=LegacyMachineAuth
    )

@bp.route("/induction/<int:machine_id>/import", methods=["POST", "GET"])
@login_required
def induction_import(machine_id):
    machine = db.get_or_404(Machine, machine_id)

    member: Member = g.member

    class ImportForm(FlaskForm):
        submit_label = "Import"

        secret = fields.StringField('Secret',[validators.Length(max=Machine.legacy_password.type.length)]) 

    import_form = ImportForm(request.form);

    secret_error = ''
    now=datetime.now(timezone.utc)

    if import_form.validate_on_submit():
        
        if machine.legacy_password == import_form.secret.data:
            #Add Induction
            secret_error = "adding induction"

            if not machine.is_member_inducted(member) :
                insert_stmt = insert(Induction).values(
                    member_id=member.id,
                    machine_id=machine.id,
                    inducted_on=now
                )

                db.session.execute(insert_stmt)

                create_audit_log(
                    "induction",
                    "import",
                    data = {
                        "machine": {
                            "id": machine.id,
                            "name": machine.name
                        },
                        "inductee": member.id
                    },
                    member=member
                )

                db.session.commit()

                flash("Induction imported")
                return redirect(url_for("induction.machine", machine_id=machine_id))
                
        else:
            secret_error = "Secret Error, check capitalisation or spaces."

    return render_template(
        "machine_induction_import.html",
        secret_error=secret_error,
        machine=machine,
        import_form=import_form
    );
