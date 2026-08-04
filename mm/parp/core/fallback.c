// SPDX-License-Identifier: GPL-2.0
#include "../internal.h"

bool parp_fallback_is_native(enum parp_fallback_reason reason)
{
	return reason != PARP_FALLBACK_NONE;
}
