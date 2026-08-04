// SPDX-License-Identifier: GPL-2.0
#include "../internal.h"

bool parp_not_expired(u64 expires_ns, u64 now_ns)
{
	return now_ns < expires_ns;
}
