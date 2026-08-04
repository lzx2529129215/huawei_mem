// SPDX-License-Identifier: GPL-2.0
#include "../internal.h"

unsigned int parp_app_prior_bin(u16 score)
{
	return min_t(unsigned int, score / 8192, 3);
}
