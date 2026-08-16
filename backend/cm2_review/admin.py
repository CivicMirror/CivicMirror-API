from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ActionForm
from django.core.exceptions import ValidationError
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import action, display

from cm2_elections.models import Person
from cm2_review.workflow import add_review_note, supersede_review_case, transition_review_case

from .models import IdentityReviewCase, IdentityReviewSuggestion


class IdentityReviewSuggestionInline(TabularInline):
    model = IdentityReviewSuggestion
    extra = 0
    autocomplete_fields = ("suggested_person",)


class ReviewCaseActionForm(ActionForm):
    target_person_public_id = forms.CharField(
        required=False,
        help_text="Public ID of the target person for link/merge actions.",
    )
    target_case_public_id = forms.CharField(
        required=False,
        help_text="Public ID of the superseding case for the supersede action.",
    )
    note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Note text for the add-note action.",
    )


@admin.register(IdentityReviewCase)
class IdentityReviewCaseAdmin(ModelAdmin):
    _REOPENABLE_STATUSES = {IdentityReviewCase.Status.OPEN, IdentityReviewCase.Status.DEFERRED}

    list_display = ("case_type_display", "status_display", "created_at", "reviewed_at", "reviewed_by", "has_private_evidence")
    list_filter = ("status", "case_type", "has_private_evidence")
    search_fields = ("public_id", "deduplication_key", "provisional_person__canonical_name")
    autocomplete_fields = (
        "source_record",
        "provisional_person",
        "result_choice",
        "reviewed_by",
        "superseded_by",
    )
    readonly_fields = (
        "id",
        "public_id",
        "deduplication_key",
        "created_at",
        "updated_at",
        "evidence_comparison",
        "status",
        "resolution_action",
        "reviewed_by",
        "reviewed_at",
        "superseded_by",
        "notes",
        "case_type",
        "has_private_evidence",
    )
    inlines = (IdentityReviewSuggestionInline,)
    action_form = ReviewCaseActionForm
    actions = (
        "confirm_new",
        "defer_cases",
        "reject_cases",
        "link_existing_cases",
        "merge_people_cases",
        "supersede_cases",
        "add_note_to_cases",
    )
    actions_row = ("confirm_new_row", "defer_case_row", "reject_case_row")
    actions_detail = ("confirm_new_row", "defer_case_row", "reject_case_row")
    fieldsets = (
        (None, {"fields": ("public_id", "case_type", "status", "has_private_evidence")}),
        ("Evidence comparison", {"fields": ("evidence_comparison",)}),
        (
            "Resolution",
            {"fields": ("resolution_action", "reviewed_by", "reviewed_at", "notes", "superseded_by")},
        ),
        ("Metadata", {"fields": ("id", "deduplication_key", "created_at", "updated_at")}),
    )

    @display(
        description="Case Type",
        ordering="case_type",
        label={
            IdentityReviewCase.CaseType.PERSON_IDENTITY: "info",
            IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH: "warning",
            IdentityReviewCase.CaseType.UNRESOLVED_RESULT_CHOICE: "danger",
        },
    )
    def case_type_display(self, obj):
        return obj.get_case_type_display()

    @display(
        description="Status",
        ordering="status",
        label={
            IdentityReviewCase.Status.OPEN: "warning",
            IdentityReviewCase.Status.APPROVED: "success",
            IdentityReviewCase.Status.REJECTED: "danger",
            IdentityReviewCase.Status.DEFERRED: "info",
            IdentityReviewCase.Status.SUPERSEDED: "info",
        },
    )
    def status_display(self, obj):
        return obj.get_status_display()

    def _redirect_back(self, request):
        return redirect(request.META.get("HTTP_REFERER") or reverse("admin:cm2_review_identityreviewcase_changelist"))

    @action(description="Confirm as distinct person")
    def confirm_new_row(self, request, object_id):
        review_case = IdentityReviewCase.objects.get(pk=object_id)
        if review_case.status in self._REOPENABLE_STATUSES:
            transition_review_case(
                review_case,
                reviewer=request.user,
                status=IdentityReviewCase.Status.APPROVED,
                action=IdentityReviewCase.ResolutionAction.CONFIRM_NEW,
            )
            self.message_user(request, "Confirmed as a distinct person.", messages.SUCCESS)
        else:
            self.message_user(request, "This case is not open or deferred.", messages.WARNING)
        return self._redirect_back(request)

    @action(description="Defer")
    def defer_case_row(self, request, object_id):
        review_case = IdentityReviewCase.objects.get(pk=object_id)
        if review_case.status == IdentityReviewCase.Status.OPEN:
            transition_review_case(
                review_case,
                reviewer=request.user,
                status=IdentityReviewCase.Status.DEFERRED,
                action=IdentityReviewCase.ResolutionAction.DEFER,
            )
            self.message_user(request, "Deferred.", messages.SUCCESS)
        else:
            self.message_user(request, "Only open cases can be deferred.", messages.WARNING)
        return self._redirect_back(request)

    @action(description="Reject")
    def reject_case_row(self, request, object_id):
        review_case = IdentityReviewCase.objects.get(pk=object_id)
        if review_case.status in self._REOPENABLE_STATUSES:
            transition_review_case(
                review_case,
                reviewer=request.user,
                status=IdentityReviewCase.Status.REJECTED,
                action=IdentityReviewCase.ResolutionAction.REJECT,
            )
            self.message_user(request, "Rejected.", messages.SUCCESS)
        else:
            self.message_user(request, "This case is not open or deferred.", messages.WARNING)
        return self._redirect_back(request)

    @admin.display(description="Evidence comparison")
    def evidence_comparison(self, obj):
        rows = []
        if obj.provisional_person is not None:
            rows.append(("Provisional person", obj.provisional_person.canonical_name))
        source = obj.source_record
        if source is not None:
            rows.append(("Source reported name", source.reported_name))
            rows.append(("Source ballot name", source.ballot_name or "—"))
            rows.append(("Protected address", source.protected_address or "—"))
            rows.append(("Protected phone", source.protected_phone or "—"))
            rows.append(("Protected email", source.protected_email or "—"))
        rows.append(("Supporting evidence", obj.supporting_evidence or {}))
        rows.append(("Conflicting evidence", obj.conflicting_evidence or {}))
        row_html = format_html_join(
            "\n",
            "<tr><th style='text-align:left;padding-right:1em;vertical-align:top'>{}</th><td>{}</td></tr>",
            ((label, value) for label, value in rows),
        )
        return format_html("<table>{}</table>", row_html)

    @admin.action(description="Confirm selected cases as distinct people")
    def confirm_new(self, request, queryset):
        total = queryset.count()
        updated = 0
        for review_case in queryset.filter(status__in=self._REOPENABLE_STATUSES):
            transition_review_case(
                review_case,
                reviewer=request.user,
                status=IdentityReviewCase.Status.APPROVED,
                action=IdentityReviewCase.ResolutionAction.CONFIRM_NEW,
            )
            updated += 1
        skipped = total - updated
        if skipped:
            self.message_user(
                request,
                f"Confirmed {updated} review case(s); {skipped} skipped (not open or deferred).",
                messages.WARNING,
            )
        else:
            self.message_user(request, f"Confirmed {updated} review case(s).", messages.SUCCESS)

    @admin.action(description="Defer selected review cases")
    def defer_cases(self, request, queryset):
        updated = 0
        for review_case in queryset.filter(status=IdentityReviewCase.Status.OPEN):
            transition_review_case(
                review_case,
                reviewer=request.user,
                status=IdentityReviewCase.Status.DEFERRED,
                action=IdentityReviewCase.ResolutionAction.DEFER,
            )
            updated += 1
        self.message_user(request, f"Deferred {updated} review case(s).", messages.SUCCESS)

    @admin.action(description="Reject selected review cases (disputes the provisional person)")
    def reject_cases(self, request, queryset):
        total = queryset.count()
        updated = 0
        for review_case in queryset.filter(status__in=self._REOPENABLE_STATUSES):
            transition_review_case(
                review_case,
                reviewer=request.user,
                status=IdentityReviewCase.Status.REJECTED,
                action=IdentityReviewCase.ResolutionAction.REJECT,
            )
            updated += 1
        skipped = total - updated
        if skipped:
            self.message_user(
                request,
                f"Rejected {updated} review case(s); {skipped} skipped (not open or deferred).",
                messages.WARNING,
            )
        else:
            self.message_user(request, f"Rejected {updated} review case(s).", messages.SUCCESS)

    @admin.action(description="Link selected cases to target person (enter target person public ID above)")
    def link_existing_cases(self, request, queryset):
        target_person = self._resolve_target_person(request)
        if target_person is None:
            return
        total = queryset.count()
        updated, failed, errors = self._apply_bulk_action(
            queryset.filter(status__in=self._REOPENABLE_STATUSES),
            lambda review_case: transition_review_case(
                review_case,
                reviewer=request.user,
                status=IdentityReviewCase.Status.APPROVED,
                action=IdentityReviewCase.ResolutionAction.LINK_EXISTING,
                target_person=target_person,
            ),
        )
        skipped = total - updated - failed
        self._report_bulk_result(
            request,
            success_verb=f"Linked {updated} review case(s) to {target_person.canonical_name}",
            failure_verb="could not be linked",
            failed=failed,
            errors=errors,
            skipped=skipped,
        )

    @admin.action(description="Merge selected cases into target person (enter target person public ID above)")
    def merge_people_cases(self, request, queryset):
        target_person = self._resolve_target_person(request)
        if target_person is None:
            return
        total = queryset.count()
        updated, failed, errors = self._apply_bulk_action(
            queryset.filter(status__in=self._REOPENABLE_STATUSES),
            lambda review_case: transition_review_case(
                review_case,
                reviewer=request.user,
                status=IdentityReviewCase.Status.APPROVED,
                action=IdentityReviewCase.ResolutionAction.MERGE_PEOPLE,
                target_person=target_person,
            ),
        )
        skipped = total - updated - failed
        self._report_bulk_result(
            request,
            success_verb=f"Merged {updated} review case(s) into {target_person.canonical_name}",
            failure_verb="could not be merged",
            failed=failed,
            errors=errors,
            skipped=skipped,
        )

    @admin.action(description="Supersede selected cases with target case (enter target case public ID above)")
    def supersede_cases(self, request, queryset):
        target_public_id = request.POST.get("target_case_public_id", "").strip()
        if not target_public_id:
            self.message_user(request, "Provide a target case public ID to supersede with.", messages.ERROR)
            return
        target_case = IdentityReviewCase.objects.filter(public_id=target_public_id).first()
        if target_case is None:
            self.message_user(request, f"No review case found with public ID {target_public_id}.", messages.ERROR)
            return
        updated, failed, errors = self._apply_bulk_action(
            queryset,
            lambda review_case: supersede_review_case(review_case, superseded_by=target_case, actor=request.user),
        )
        self._report_bulk_result(
            request,
            success_verb=f"Superseded {updated} review case(s)",
            failure_verb="could not be superseded",
            failed=failed,
            errors=errors,
        )

    @admin.action(description="Add note to selected open/deferred cases (enter note text above)")
    def add_note_to_cases(self, request, queryset):
        note = request.POST.get("note", "").strip()
        if not note:
            self.message_user(request, "Provide note text to add a note.", messages.ERROR)
            return
        excluded_statuses = [
            IdentityReviewCase.Status.APPROVED,
            IdentityReviewCase.Status.REJECTED,
            IdentityReviewCase.Status.SUPERSEDED,
        ]
        updated, failed, errors = self._apply_bulk_action(
            queryset.exclude(status__in=excluded_statuses),
            lambda review_case: add_review_note(review_case, actor=request.user, note=note),
        )
        self._report_bulk_result(
            request,
            success_verb=f"Added a note to {updated} review case(s)",
            failure_verb="could not receive the note",
            failed=failed,
            errors=errors,
        )

    def _apply_bulk_action(self, queryset, apply_fn):
        """Run apply_fn per item, isolating ValidationErrors so one bad case doesn't abort the batch."""
        updated = 0
        failed = 0
        errors = []
        for review_case in queryset:
            try:
                apply_fn(review_case)
            except ValidationError as exc:
                failed += 1
                errors.append(f"{review_case.public_id}: {'; '.join(exc.messages)}")
            else:
                updated += 1
        return updated, failed, errors

    def _report_bulk_result(self, request, *, success_verb, failure_verb, failed, errors, skipped=0):
        skipped_note = f"; {skipped} skipped (not open or deferred)" if skipped else ""
        if failed:
            detail = " | ".join(errors)
            self.message_user(
                request,
                f"{success_verb}{skipped_note}; {failed} review case(s) {failure_verb}: {detail}",
                messages.WARNING,
            )
        elif skipped:
            self.message_user(request, f"{success_verb}{skipped_note}.", messages.WARNING)
        else:
            self.message_user(request, f"{success_verb}.", messages.SUCCESS)

    def _resolve_target_person(self, request):
        target_public_id = request.POST.get("target_person_public_id", "").strip()
        if not target_public_id:
            self.message_user(request, "Provide a target person public ID for this action.", messages.ERROR)
            return None
        target_person = Person.objects.filter(public_id=target_public_id).first()
        if target_person is None:
            self.message_user(request, f"No person found with public ID {target_public_id}.", messages.ERROR)
            return None
        return target_person


@admin.register(IdentityReviewSuggestion)
class IdentityReviewSuggestionAdmin(ModelAdmin):
    list_display = ("review_case", "rank", "suggested_person", "external_scheme", "uses_private_evidence")
    list_filter = ("external_scheme", "uses_private_evidence")
    search_fields = ("review_case__public_id", "suggested_person__canonical_name", "external_identifier")
    autocomplete_fields = ("review_case", "suggested_person")
