// SPDX-License-Identifier: GPL-2.0
#include "../internal.h"

u16 parp_q15_mul(u16 a, u16 b)
{
	u32 product = (u32)min_t(u16, a, PARP_Q15_ONE) *
		      min_t(u16, b, PARP_Q15_ONE);

	return min_t(u32, (product + (1U << 14)) >> 15, PARP_Q15_ONE);
}

s16 parp_q15_sat_add(s16 a, s16 b)
{
	s32 sum = (s32)a + b;

	return clamp_t(s32, sum, S16_MIN, S16_MAX);
}

static const struct parp_binding *
parp_find_binding(const struct parp_snapshot *snapshot, u64 domain_id)
{
	unsigned int i;

	for (i = 0; i < min_t(u32, snapshot->nr_bindings,
			      PARP_MAX_DOMAINS); i++)
		if (snapshot->bindings[i].active &&
		    snapshot->bindings[i].domain_id == domain_id)
			return &snapshot->bindings[i];
	return NULL;
}

static const struct parp_app_prior *
parp_find_prior(const struct parp_snapshot *snapshot, u32 app_id)
{
	unsigned int i;

	for (i = 0; i < min_t(u32, snapshot->nr_priors, PARP_MAX_APPS); i++)
		if (snapshot->priors[i].valid &&
		    snapshot->priors[i].app_id == app_id)
			return &snapshot->priors[i];
	return NULL;
}

struct parp_decision parp_engine_score(const struct parp_snapshot *snapshot,
				       const struct parp_page_sample *sample)
{
	const struct parp_binding *binding;
	const struct parp_app_prior *prior;
	struct parp_page_sample enriched = *sample;
	struct parp_decision decision = {
		.original_action = PARP_ACTION_NATIVE,
		.proposed_action = PARP_ACTION_NATIVE,
		.applied_action = PARP_ACTION_NATIVE,
	};
	u64 now = ktime_get_mono_fast_ns();

	if (!snapshot) {
		decision.fallback = PARP_FALLBACK_NO_DOMAIN;
		return decision;
	}
	binding = parp_find_binding(snapshot, sample->domain_id);
	if (!binding) {
		decision.fallback = PARP_FALLBACK_NO_BINDING;
		return decision;
	}
	if (now >= binding->expires_ns || now >= snapshot->expires_ns) {
		decision.fallback = PARP_FALLBACK_EXPIRED;
		return decision;
	}
	prior = parp_find_prior(snapshot, binding->app_id);
	if (!prior || now >= prior->expires_ns) {
		decision.fallback = PARP_FALLBACK_EXPIRED;
		return decision;
	}
	if (prior->model_version != binding->model_version) {
		decision.fallback = PARP_FALLBACK_MODEL_VERSION;
		return decision;
	}
	if (!sample->evidence_valid) {
		decision.fallback = PARP_FALLBACK_NO_EVIDENCE;
		return decision;
	}
	if (sample->dirty || sample->writeback || sample->unevictable) {
		decision.fallback = PARP_FALLBACK_UNSAFE_FOLIO;
		return decision;
	}

	enriched.app_prior_q15 = prior->use_score_q15;
	if (sample->type == PARP_PAGE_FILE) {
		decision.score_q15 = parp_file_future_score(&enriched);
		if (decision.score_q15 >= 24576)
			decision.proposed_action = sample->resident ?
				PARP_ACTION_PROTECT :
				PARP_ACTION_PREFETCH_CANDIDATE;
		else if (decision.score_q15 <= 4096)
			decision.proposed_action = PARP_ACTION_RECLAIM_BIAS;
	} else {
		decision.score_q15 = parp_anon_cold_score(&enriched);
		if (decision.score_q15 >= 24576)
			decision.proposed_action = PARP_ACTION_RECLAIM_BIAS;
	}
	return decision;
}
