// SPDX-License-Identifier: GPL-2.0
#include "../internal.h"

bool parp_budget_allow(unsigned int used, unsigned int limit)
{
	return used < limit;
}
