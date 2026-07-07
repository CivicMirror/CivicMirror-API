from django.contrib import admin

from .models import Candidate, DistrictRecord, Election, ElectionCycle, MeasureOption, Race


@admin.register(ElectionCycle)
class ElectionCycleAdmin(admin.ModelAdmin):
    list_display = ('cycle_year', 'description', 'cycle_start', 'cycle_end')
    ordering = ('-cycle_year',)


@admin.action(description="Fetch Ohio results now")
def fetch_ohio_results(modeladmin, request, queryset):
    # Local import: avoids loading the results app's Celery task graph
    # (and, transitively, the OH adapter's browser-automation imports) for
    # every admin page load — only needed when this action actually runs.
    from results.tasks import ingest_official_results

    oh_elections = queryset.filter(state='OH')
    skipped = queryset.exclude(state='OH').count()

    for election in oh_elections:
        ingest_official_results.delay('OH', election.pk)

    if oh_elections:
        modeladmin.message_user(
            request,
            f"Queued Ohio results fetch for {oh_elections.count()} election(s). "
            "This runs a real browser (nodriver + Xvfb) and can take 30-60+ "
            "seconds per election — check ops.SyncLog or the Race/OfficialResult "
            "records shortly to confirm it completed.",
        )
    if skipped:
        modeladmin.message_user(
            request,
            f"Skipped {skipped} non-Ohio election(s) — this action only applies to state=OH.",
            level='warning',
        )


@admin.register(Election)
class ElectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'election_date', 'jurisdiction_level', 'state', 'status', 'last_synced_at')
    list_filter = ('status', 'jurisdiction_level', 'state')
    search_fields = ('name', 'source_id', 'state')
    readonly_fields = ('last_synced_at',)
    ordering = ('-election_date',)
    actions = [fetch_ohio_results]


@admin.register(Race)
class RaceAdmin(admin.ModelAdmin):
    list_display = ('office_title', 'election', 'race_type', 'source', 'certification_status', 'race_status')
    list_filter = ('race_type', 'source', 'certification_status', 'race_status')
    search_fields = ('office_title', 'jurisdiction', 'ocd_division_id')
    raw_id_fields = ('election',)
    readonly_fields = ('last_synced_at', 'normalized_office_title', 'canonical_key')


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ('name', 'party', 'race', 'incumbent', 'candidate_status')
    list_filter = ('candidate_status', 'incumbent')
    search_fields = ('name', 'party', 'fec_candidate_id', 'bioguide_id')
    raw_id_fields = ('race',)


@admin.register(MeasureOption)
class MeasureOptionAdmin(admin.ModelAdmin):
    list_display = ('option_label', 'race')
    raw_id_fields = ('race',)


@admin.register(DistrictRecord)
class DistrictRecordAdmin(admin.ModelAdmin):
    list_display = ('name', 'state', 'district_type', 'ocd_division_id', 'fips_code')
    list_filter = ('state', 'district_type')
    search_fields = ('name', 'ocd_division_id', 'fips_code')
