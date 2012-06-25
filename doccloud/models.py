from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.conf import settings
from django.db import models
from datetime import datetime
from documentcloud import DocumentCloud
from django_extensions.db.fields import AutoSlugField, CreationDateTimeField

PRIVACY_LVLS = (
    ('private', 'Private (only viewable by those with permission to this doc)'),
    ('public', 'Public (viewable by anyone)'),
    ('organization', 'Organization (viewable by users in your organization)')
)


def get_client():
    return DocumentCloud(settings.DOCUMENTCLOUD_USERNAME,
                         settings.DOCUMENTCLOUD_PASS)


def get_dc_file(id):
    t_client = get_client()
    return t_client.documents.get(id)


def put_file(file, title, access_level, **kwargs):
    t_client = get_client()
    dc_obj = t_client.documents.upload(pdf=file,
                                       title=title,
                                       access=access_level,
                                       description=kwargs.get('description', None),
                                       project=kwargs.get('project', None),
                                       secure=True)
    file.seek(0)
    return (dc_obj.id, dc_obj.canonical_url)


def rm_file(id):
    try:
        get_dc_file(id).delete()
    except Exception as e:
        return False


class DocumentCloudProperties(models.Model):
    dc_id = models.CharField(max_length=300, blank=False, null=False)
    dc_url = models.URLField(verify_exists=False, max_length=200, null=False, blank=False)

    updatable_properties = ('title', 'source', 'description',
                            'related_article', 'published_url', 'access', 'data')

    def __init__(self, *args, **kwargs):
        vals = None
        if "file" in kwargs and "title" in kwargs and "access_level" in kwargs:
                file = kwargs.pop('file')
                title = kwargs.pop('title')
                access_level = kwargs.pop('access_level')
                description = kwargs.pop('description', None)
                vals = put_file(file, title, access_level, description=description)
        super(DocumentCloudProperties, self).__init__(*args, **kwargs)
        #set values l8r so values aren't overwritten
        if vals is not None:
            self.dc_id = vals[0]
            self.dc_url = vals[1]

    def put_changes(self, **kwargs):
        """docstring for put_changes"""
        try:
            dc_obj = get_dc_file(self.dc_id)
            for key, value in kwargs.iteritems():
                # Update only updatable properties, and don't store 'None'.
                if key in self.updatable_properties and value is not None:
                    setattr(dc_obj, key, value)
            dc_obj.save()
        except Exception as e:
            raise e

    def _doc_data(self):
        try:
            dc_obj = get_dc_file(self.dc_id)
            return dc_obj.data
        except Exception, e:
            raise e

    def update_access(self, access):
        if self.dc_id is None and self.dc_url is None:
            return False  # obj not set yet
        try:
            dc_obj = get_dc_file(self.dc_id)
            dc_obj.access = access
            dc_obj.save()
        except Exception as e:
            return False  # taking suggestions on handling mgmt issues n admin

    def delete(self, *args, **kwargs):
        #no effective way of dealing with errors on DC cloud side
        #unless we create a custom template for managing documents
        rm_file(self.dc_id)
        #so if rm_file don't complete we orphan the dc cloud doc
        super(DocumentCloudProperties, self).delete(*args, **kwargs)


class Document(models.Model):
    """
    see documentcloud api https://www.documentcloud.org/help/api
    upload_to path is ...
    https://docs.djangoproject.com/en/dev/ref/models/fields/#django.db.models.FileField.upload_to
    """
    file = models.FileField(upload_to=settings.DOCUMENTS_PATH, max_length=255)
    slug = AutoSlugField(populate_from=('title',))
    user = models.ForeignKey(User, blank=True, null=True)
    title = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    created_at = CreationDateTimeField(db_index=True)
    updated_at = models.DateTimeField(editable=False, auto_now=True, blank=True, db_index=True)
    dc_properties = models.ForeignKey(DocumentCloudProperties, blank=True, null=True)
    access_level = models.CharField(max_length=32, choices=PRIVACY_LVLS)

    class Meta:
        verbose_name_plural = 'Documents'
        ordering = ['created_at']

    def __unicode__(self):
        return self.title

    _dc_data = None

    def dc_data():
        doc = "The dc_data property is for setting k:v pairs that get sent to documentcloud"

        def fget(self):
            if self.dc_properties:
                self._dc_data = self.dc_properties._doc_data()
            return self._dc_data

        def fset(self, value):
            if isinstance(value, dict):
                self._dc_data = value
                if self.dc_properties:
                    self.dc_properties.put_changes(data=self._dc_data)
            else:
                raise TypeError('This value must be a dictionary.')
        return locals()
    dc_data = property(**dc_data())

    def get_absolute_url(self):
        if self.dc_properties is not None:
            return self.dc_properties.dc_url
        return self.file.url

    def connect_dc_doc(self):
        prop_kwargs = {
            'file': self.file,
            'title': self.title,
            'access_level': self.access_level,
            'description': self.description
        }
        if self.dc_data:
            prop_kwargs['data'] = self.dc_data
        dc_props = DocumentCloudProperties(**prop_kwargs)
        dc_props.save()
        self.dc_properties = dc_props

    def delete(self, *args, **kwargs):
        self.dc_properties.delete()
        if self.dc_properties is not None:
            return False  # document didn't delete, admin view error msgs?
        super(Document, self).delete(*args, **kwargs)

    def link(self):
        return '<a href="%s" target="_blank">%s</a>' % (self.get_absolute_url(), "link")
