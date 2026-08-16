from cm2_review.models import IdentityReviewCase


def open_review_case_count(request):
    count = IdentityReviewCase.objects.filter(status=IdentityReviewCase.Status.OPEN).count()
    return count or None
