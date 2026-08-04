// SPDX-License-Identifier: GPL-2.0
#include "../internal.h"

struct parp_stats parp_stats;

void parp_stats_account(const struct parp_decision *decision)
{
	atomic64_inc(&parp_stats.scored);
	atomic64_inc(&parp_stats.proposed[decision->proposed_action]);
	atomic64_inc(&parp_stats.fallback[decision->fallback]);
}
