from django.db import models


class UserProfile(models.Model):
    uid = models.CharField(max_length=128, unique=True)
    display_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def vote_count(self):
        return MockVote.objects.filter(uid=self.uid).count()

    @property
    def submission_count(self):
        from elections.models import Race
        return Race.objects.filter(submitted_by_uid=self.uid, source=Race.Source.COMMUNITY).count()

    def __str__(self):
        return f'UserProfile({self.uid})'


class MockVote(models.Model):
    uid = models.CharField(max_length=128, db_index=True)
    race = models.ForeignKey('elections.Race', on_delete=models.CASCADE, related_name='mock_votes')
    candidate_ids = models.JSONField(null=True, blank=True)
    measure_option_id = models.IntegerField(null=True, blank=True)
    ranked_selections = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('uid', 'race')]

    @property
    def selection_type(self):
        if self.measure_option_id is not None:
            return 'measure_option'
        return 'candidate'

    def __str__(self):
        return f'MockVote(uid={self.uid}, race_id={self.race_id})'
