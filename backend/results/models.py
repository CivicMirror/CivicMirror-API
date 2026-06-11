import django
from django.db import models
from django.db.models import F, Q, Value
from django.db.models.functions import Coalesce


def _check_constraint(*, condition, name):
    keyword = 'condition' if django.VERSION >= (5, 1) else 'check'
    return models.CheckConstraint(name=name, **{keyword: condition})


class OfficialResult(models.Model):
    class ResultType(models.TextChoices):
        OFFICIAL = 'official', 'Official'
        UNOFFICIAL = 'unofficial', 'Unofficial'

    race = models.ForeignKey('elections.Race', on_delete=models.CASCADE, related_name='official_results')
    candidate = models.ForeignKey(
        'elections.Candidate',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='official_results',
    )
    measure_option = models.ForeignKey(
        'elections.MeasureOption',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='official_results',
    )
    vote_count = models.BigIntegerField(default=0)
    vote_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    certified_at = models.DateTimeField(null=True, blank=True)
    source_url = models.URLField(blank=True)
    result_type = models.CharField(max_length=20, default=ResultType.UNOFFICIAL, choices=ResultType.choices)
    is_winner = models.BooleanField(null=True, blank=True)
    round_number = models.PositiveSmallIntegerField(null=True, blank=True)
    jurisdiction_fragment = models.CharField(max_length=255, blank=True)
    is_write_in_aggregate = models.BooleanField(default=False)
    raw_payload = models.JSONField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['race', 'round_number'])]
        constraints = [
            _check_constraint(
                condition=(
                    Q(is_write_in_aggregate=True)
                    | (Q(candidate__isnull=False) & Q(measure_option__isnull=True))
                    | (Q(candidate__isnull=True) & Q(measure_option__isnull=False))
                ),
                name='result_target_valid',
            ),
            # Mirrors the update_or_create natural key in results.tasks; COALESCE
            # treats NULL candidate/measure_option/round_number as equal so
            # concurrent retries can't insert duplicate rows.
            models.UniqueConstraint(
                F('race'),
                Coalesce('candidate', Value(0)),
                Coalesce('measure_option', Value(0)),
                Coalesce('round_number', Value(-1)),
                F('jurisdiction_fragment'),
                name='official_result_natural_key',
            ),
        ]
        ordering = ['round_number', '-vote_count', 'id']

    def __str__(self) -> str:
        return f'{self.race.office_title} - {self.vote_count}'
