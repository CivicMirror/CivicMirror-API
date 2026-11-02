from django.urls import reverse

from cm2_elections.models import Contest
from cm2_review.models import IdentityReviewCase

_REVIEW_KPI_TYPES = (
    (IdentityReviewCase.CaseType.PERSON_IDENTITY, "New Person"),
    (IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH, "Fuzzy Match"),
    (IdentityReviewCase.CaseType.UNRESOLVED_RESULT_CHOICE, "Unmatched Write-in"),
)


def dashboard_callback(request, context):
    open_cases = IdentityReviewCase.objects.filter(status=IdentityReviewCase.Status.OPEN)
    review_url = reverse("admin:cm2_review_identityreviewcase_changelist")
    context["review_kpis"] = [
        {
            "label": label,
            "count": open_cases.filter(case_type=case_type).count(),
            "url": f"{review_url}?status__exact={IdentityReviewCase.Status.OPEN}&case_type__exact={case_type}",
        }
        for case_type, label in _REVIEW_KPI_TYPES
    ]
    contest_url = reverse("admin:cm2_elections_contest_changelist")
    context["pending_contests"] = {
        "count": Contest.objects.filter(result_status=Contest.ResultStatus.PENDING).count(),
        "url": f"{contest_url}?result_status__exact={Contest.ResultStatus.PENDING}",
    }
    return context
