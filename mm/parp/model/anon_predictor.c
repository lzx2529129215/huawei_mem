// SPDX-License-Identifier: GPL-2.0
#include "../internal.h"

u16 parp_anon_cold_score(const struct parp_page_sample *sample)
{
	u32 recent;
	u32 cold;

	if (!sample->evidence_valid)
		return 0;
	recent = min_t(u32, sample->accesses_10s * 4 +
		       sample->accesses_30s * 2 + sample->accesses_60s, 32767);
	cold = PARP_Q15_ONE - recent;
	cold = (cold + (PARP_Q15_ONE - sample->active_ratio_q15)) / 2;
	/* app prior may modulate evidence, but can never create it. */
	return parp_q15_mul(cold, PARP_Q15_ONE -
			    min_t(u16, sample->app_prior_q15, PARP_Q15_ONE));
}
