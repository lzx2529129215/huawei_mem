// SPDX-License-Identifier: GPL-2.0
#include "../internal.h"

u16 parp_file_future_score(const struct parp_page_sample *sample)
{
	u16 score;

	score = parp_q15_mul(sample->app_prior_q15, sample->next_state_q15);
	score = parp_q15_mul(score, sample->support_q15);
	score = parp_q15_mul(score, sample->stability_q15);
	return parp_q15_mul(score, sample->freshness_q15);
}
