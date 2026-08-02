// SPDX-License-Identifier: GPL-2.0
/*
 * 内核外的 L0.3A 快速路径等价微基准。它只比较实现中的三层固定成本：
 * disabled gate、enabled filter 和 target hash/update，不模拟 tracepoint。
 */

#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#define ITERATIONS 10000000ULL
#define SLOT_COUNT 1024U

struct bench_table {
	volatile bool enabled;
	uint64_t target_memcg;
	int target_nid;
	uint32_t type_mask;
	uint64_t slots[SLOT_COUNT];
};

static inline bool observe(struct bench_table *table, uint64_t key,
		uint64_t memcg, int nid, uint32_t type)
{
	if (__builtin_expect(!table->enabled, 1))
		return false;
	if (memcg != table->target_memcg || nid != table->target_nid ||
	    !(type & table->type_mask))
		return false;
	table->slots[key & (SLOT_COUNT - 1)]++;
	return true;
}

static uint64_t now_ns(void)
{
	struct timespec time;

	if (clock_gettime(CLOCK_MONOTONIC, &time))
		exit(EXIT_FAILURE);
	return (uint64_t)time.tv_sec * 1000000000ULL + time.tv_nsec;
}

static double run(struct bench_table *table, uint64_t memcg, int nid,
		uint32_t type, uint64_t *accepted)
{
	uint64_t begin;
	uint64_t end;
	uint64_t i;
	uint64_t count = 0;

	begin = now_ns();
	for (i = 0; i < ITERATIONS; i++)
		count += observe(table, i, memcg, nid, type);
	end = now_ns();
	*accepted = count;
	return (double)(end - begin) / (double)ITERATIONS;
}

int main(void)
{
	struct bench_table table = {
		.enabled = false,
		.target_memcg = 42,
		.target_nid = 1,
		.type_mask = 3,
	};
	uint64_t accepted;
	double disabled;
	double non_target;
	double target;

	disabled = run(&table, 42, 1, 1, &accepted);
	if (accepted)
		return EXIT_FAILURE;
	table.enabled = true;
	non_target = run(&table, 99, 1, 1, &accepted);
	if (accepted)
		return EXIT_FAILURE;
	target = run(&table, 42, 1, 1, &accepted);
	if (accepted != ITERATIONS)
		return EXIT_FAILURE;
	printf("iterations=%" PRIu64 " disabled_ns=%.3f non_target_ns=%.3f "
	       "target_ns=%.3f\n", (uint64_t)ITERATIONS, disabled,
	       non_target, target);
	return EXIT_SUCCESS;
}
