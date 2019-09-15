from django.contrib import admin
from . import models

class TweetAdmin(admin.ModelAdmin):
    list_display = ('id', 'tweet_id', 'text', 'user_name', 'created_at')
    search_fields=['text']
    ordering = ['-id']

class UserAdmin(admin.ModelAdmin):
    list_display = ('id', 'user_id', 'name', 'screen_name', 'created_at')
    search_fields=['name', 'screen_name']
    ordering = ['-id']

admin.site.register(models.Tweet, TweetAdmin)
admin.site.register(models.User, UserAdmin)
