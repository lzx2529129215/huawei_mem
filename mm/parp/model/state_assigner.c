// SPDX-License-Identifier: GPL-2.0
#include "../internal.h"

int parp_assign_state(const s16 *features, const s16 *centers,
		      unsigned int nr_features, unsigned int nr_states,
		      u32 unknown_threshold)
{
	u64 best = U64_MAX;
	unsigned int state, feature, best_state = 0;

	for (state = 0; state < min(nr_states, (unsigned int)PARP_MAX_STATES);
	     state++) {
		u64 distance = 0;

		for (feature = 0; feature < nr_features; feature++) {
			s32 delta = features[feature] -
				    centers[state * nr_features + feature];
			distance += (u64)delta * delta;
		}
		if (distance < best) {
			best = distance;
			best_state = state;
		}
	}
	return best > unknown_threshold ? -1 : best_state;
}
