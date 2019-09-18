from django.db import models
from django.conf import settings
from datetime import datetime, timedelta
from email.utils import parsedate
from django.utils import timezone
import os
import socket
from annoying.fields import JSONField
from annoying.functions import get_object_or_None

USE_TZ = getattr(settings, "USE_TZ", True)

current_timezone = timezone.get_current_timezone()


def parse_datetime(string):
    if settings.USE_TZ:
        return datetime(*(parsedate(string)[:6]), tzinfo=current_timezone)
    else:
        return datetime(*(parsedate(string)[:6]))


class User(models.Model):
    """
    https://developer.twitter.com/en/docs/tweets/data-dictionary/overview/user-object.html
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.BigIntegerField(unique=True)

    # Basic user info
    name = models.CharField("Name", max_length=200)
    screen_name = models.CharField("Screen name", max_length=50)
    location = models.CharField("Location", max_length=300)
    url = models.URLField(max_length=300, null=True)
    description = models.TextField("Description")
    protected = models.NullBooleanField("Protected", default=False)
    verified = models.NullBooleanField("Verified", default=False)

    # Engagement
    followers_count = models.IntegerField(default=0, null=True)
    friends_count = models.IntegerField(default=0, null=True)
    listed_count = models.IntegerField(default=0, null=True)
    favourites_count = models.IntegerField(default=0, null=True)
    statuses_count = models.IntegerField(default=0, null=True)

    # Timing parameters
    created_at = models.DateTimeField()

    # Profile info
    profile_banner_url = models.URLField(max_length=300, null=True)
    profile_image_url_https = models.URLField(max_length=300, null=True)
    default_profile = models.NullBooleanField("Default profile", default=False)
    default_profile_image = models.NullBooleanField(
        "Default profile image", default=False
    )

    # Entities
    entities = JSONField(blank=True, null=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __unicode__(self):
        return self.name


class Tweet(models.Model):
    """
    Selected fields from a Twitter Status object.
    Incorporates several fields from the associated User object.
    For details see https://dev.twitter.com/docs/platform-objects/tweets

    It doesn't store Geo parameters because they will be deprecatednot store 
    them because they will be deprecated.

    It doesn't store source because it isn't useful in many cases.
    """

    # Not using tweet_id for primary_key to use ForeignKey(32bit) in other models
    id = models.BigAutoField(primary_key=True)
    tweet_id = models.BigIntegerField(unique=True)

    # Basic tweet info
    text = models.CharField(max_length=280)
    truncated = models.BooleanField(default=False)

    # Basic user info
    user_id = models.BigIntegerField()

    # Timing parameters
    created_at = models.DateTimeField(db_index=True)  # should be UTC

    # none, low, or medium
    filter_level = models.CharField(max_length=6, null=True, blank=True, default=None)

    # Engagement - not likely to be very useful for streamed tweets but whatever
    reply_count = models.PositiveIntegerField(null=True, blank=True)
    retweet_count = models.PositiveIntegerField(null=True, blank=True)
    favorite_count = models.PositiveIntegerField(null=True, blank=True)

    # Relation to other tweets
    in_reply_to_status_id = models.BigIntegerField(null=True, blank=True, default=None)
    retweeted_status_id = models.BigIntegerField(null=True, blank=True, default=None)

    # Entities
    entities = JSONField(blank=True, null=True)

    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_retweet(self):
        return self.retweeted_status_id is not None

    @property
    def user_name(self):
        user = get_object_or_None(User, user_id=self.user_id)
        return user.name if user else None

    @classmethod
    def get_created_in_range(cls, start, end):
        """
        Returns all the tweets between start and end.
        """
        return cls.objects.filter(created_at__gte=start, created_at__lt=end)

    @classmethod
    def get_earliest_created_at(cls):
        """
        Returns the earliest created_at time, or None
        """
        result = cls.objects.aggregate(earliest_created_at=models.Min("created_at"))
        return result["earliest_created_at"]

    @classmethod
    def get_latest_created_at(cls):
        """
        Returns the latest created_at time, or None
        """
        result = cls.objects.aggregate(latest_created_at=models.Max("created_at"))
        return result["latest_created_at"]

    def __unicode__(self):
        return self.text


def create_or_update_from_json(raw, save_rts):
    """
    Given a *parsed* json status object, construct a new Tweet and User model.
    """

    raw_user = raw["user"]
    retweeted_status = raw.get("retweeted_status")
    if retweeted_status is None:
        retweeted_status = {"id": None}

    # Skip processing retweet
    if save_rts is False and retweeted_status["id"]:
        return

    # Replace negative counts with None to indicate missing data
    counts = {
        "reply_count": raw.get("reply_count"),
        "favorite_count": raw.get("favorite_count"),
        "retweet_count": raw.get("retweet_count"),
    }
    for key in counts:
        if counts[key] is not None and counts[key] < 0:
            counts[key] = None

    # Replace negative counts with None to indicate missing data
    user_counts = {
        "favourites_count": raw_user.get("favourites_count"),
        "followers_count": raw_user.get("followers_count"),
        "friends_count": raw_user.get("friends_count"),
        "listed_count": raw_user.get("listed_count"),
        "statuses_count": raw_user.get("statuses_count"),
    }
    for key in user_counts:
        if user_counts[key] is not None and user_counts[key] < 0:
            user_counts[key] = None

    tweet_defaults = dict(
        tweet_id=raw["id"],
        # Basic tweet info
        text=raw["text"],
        truncated=raw["truncated"],
        # Basic user info
        user_id=raw_user["id"],
        # Timing parameters
        created_at=parse_datetime(raw["created_at"]),
        # none, low, or medium
        filter_level=raw.get("filter_level"),
        # Engagement - not likely to be very useful for streamed tweets but whatever
        reply_count=counts.get("reply_count"),
        favorite_count=counts.get("favorite_count"),
        retweet_count=counts.get("retweet_count"),
        # Relation to other tweets
        in_reply_to_status_id=raw.get("in_reply_to_status_id"),
        retweeted_status_id=retweeted_status["id"],
        # Entities
        entities=raw.get("entities"),
    )

    user_defaults = dict(
        user_id=raw_user["id"],
        # Basic user info
        name=raw_user["name"],
        screen_name=raw_user["screen_name"],
        location=raw_user["location"],
        url=raw_user["url"],
        description=raw_user["description"],
        protected=raw_user["protected"],
        verified=raw_user["verified"],
        # Engagement
        followers_count=user_counts.get("followers_count"),
        friends_count=user_counts.get("friends_count"),
        listed_count=user_counts.get("listed_count"),
        favourites_count=user_counts.get("favourites_count"),
        statuses_count=user_counts.get("statuses_count"),
        # Timing parameters
        created_at=parse_datetime(raw_user["created_at"]),
        # Profile info
        profile_banner_url=raw_user.get("profile_banner_url"),
        profile_image_url_https=raw_user.get("profile_image_url_https"),
        default_profile=raw_user.get("default_profile"),
        default_profile_image=raw_user.get("default_profile_image"),
        # Entities
        entities=raw_user.get("entities"),
    )

    # get_or_update Tweet object
    tweet, tweet_created = Tweet.objects.get_or_create(
        tweet_id=raw["id"], defaults=tweet_defaults
    )
    if not tweet_created:
        for k, v in tweet_defaults.items():
            setattr(tweet, k, v)
        tweet.save()

    # get_or_update User object
    user, user_created = User.objects.get_or_create(
        user_id=raw_user["id"], defaults=user_defaults
    )
    if not user_created:
        for k, v in user_defaults.items():
            setattr(user, k, v)
        user.save()

    return tweet, user
