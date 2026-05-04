from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from hackspace_mgmt.models import db, Tag
from flask_admin.model.form import InlineFormAdmin


class TagView(ModelView):
    column_searchable_list = ['title']
    column_list = ('title',)
    column_formatters = dict()


def create_views(admin: Admin):
    admin.add_view(TagView(Tag, db.session, endpoint="tag_view", category="Access Control"))
