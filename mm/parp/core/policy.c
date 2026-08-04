// SPDX-License-Identifier: GPL-2.0
#include "../internal.h"

/* Apply remains deliberately inert until bounded budgets are validated. */
enum parp_action parp_policy_applied(enum parp_mode mode,
				     enum parp_action original,
				     enum parp_action proposed)
{
	return original;
}
