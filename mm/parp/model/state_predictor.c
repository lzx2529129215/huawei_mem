// SPDX-License-Identifier: GPL-2.0
#include "../internal.h"

u16 parp_predict_next_state(const u16 *table, unsigned int nr_states,
			    unsigned int current_state, unsigned int previous_state,
			    unsigned int duration_bin,
			    unsigned int app_prior_bin)
{
	size_t index;

	if (!nr_states || current_state >= nr_states ||
	    previous_state >= nr_states)
		return 0;
	index = (((previous_state * nr_states + current_state) * 3 +
		  min(duration_bin, 2U)) * 4 + min(app_prior_bin, 3U));
	return min_t(u16, table[index], PARP_Q15_ONE);
}
