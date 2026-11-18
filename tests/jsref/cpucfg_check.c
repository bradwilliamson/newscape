/*
 * Check the generated js/ref CPU configuration against the compiler's ABI.
 *
 * Every check is a compile-time assertion, so a wrong prcpucfg.h fails the
 * build. The program only reports success to CTest.
 */
#ifndef NEWSCAPE_PRCPUCFG_H
#error "NEWSCAPE_PRCPUCFG_H must name the generated prcpucfg.h"
#endif
#include NEWSCAPE_PRCPUCFG_H

#include <stdio.h>

#define CHECK(expr) _Static_assert(expr, #expr)

/* Sizes. NSPR's "word" (prword) is a long the size of a pointer. */
CHECK(PR_BYTES_PER_BYTE == 1);
CHECK(PR_BYTES_PER_SHORT == sizeof(short));
CHECK(PR_BYTES_PER_INT == sizeof(int));
CHECK(PR_BYTES_PER_INT64 == sizeof(long long));
CHECK(PR_BYTES_PER_LONG == sizeof(long));
CHECK(PR_BYTES_PER_FLOAT == sizeof(float));
CHECK(PR_BYTES_PER_DOUBLE == sizeof(double));
CHECK(PR_BYTES_PER_WORD == sizeof(long));
CHECK(PR_BYTES_PER_WORD == sizeof(void *));
CHECK(PR_BYTES_PER_DWORD == 8);

/* Bit counts and their log2 forms. */
CHECK(PR_BITS_PER_BYTE == 8);
CHECK(PR_BITS_PER_SHORT == 8 * sizeof(short));
CHECK(PR_BITS_PER_INT == 8 * sizeof(int));
CHECK(PR_BITS_PER_INT64 == 64);
CHECK(PR_BITS_PER_LONG == 8 * sizeof(long));
CHECK(PR_BITS_PER_FLOAT == 8 * sizeof(float));
CHECK(PR_BITS_PER_DOUBLE == 8 * sizeof(double));
CHECK(PR_BITS_PER_WORD == 8 * sizeof(long));
CHECK((1L << PR_BITS_PER_BYTE_LOG2) == PR_BITS_PER_BYTE);
CHECK((1L << PR_BITS_PER_SHORT_LOG2) == PR_BITS_PER_SHORT);
CHECK((1L << PR_BITS_PER_INT_LOG2) == PR_BITS_PER_INT);
CHECK((1L << PR_BITS_PER_INT64_LOG2) == PR_BITS_PER_INT64);
CHECK((1L << PR_BITS_PER_LONG_LOG2) == PR_BITS_PER_LONG);
CHECK((1L << PR_BITS_PER_FLOAT_LOG2) == PR_BITS_PER_FLOAT);
CHECK((1L << PR_BITS_PER_DOUBLE_LOG2) == PR_BITS_PER_DOUBLE);
CHECK((1L << PR_BITS_PER_WORD_LOG2) == PR_BITS_PER_WORD);
CHECK((1L << PR_BYTES_PER_WORD_LOG2) == PR_BYTES_PER_WORD);
CHECK((1L << PR_BYTES_PER_DWORD_LOG2) == PR_BYTES_PER_DWORD);
CHECK((1L << PR_WORDS_PER_DWORD_LOG2) == PR_BYTES_PER_DWORD / PR_BYTES_PER_WORD);

/* Alignments. */
CHECK(PR_ALIGN_OF_SHORT == _Alignof(short));
CHECK(PR_ALIGN_OF_INT == _Alignof(int));
CHECK(PR_ALIGN_OF_LONG == _Alignof(long));
CHECK(PR_ALIGN_OF_INT64 == _Alignof(long long));
CHECK(PR_ALIGN_OF_FLOAT == _Alignof(float));
CHECK(PR_ALIGN_OF_DOUBLE == _Alignof(double));
CHECK(PR_ALIGN_OF_POINTER == _Alignof(void *));
CHECK(PR_ALIGN_OF_WORD == _Alignof(long));

/* Byte order. */
#if !defined(__BYTE_ORDER__)
#error "compiler does not define __BYTE_ORDER__"
#elif __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
#if !defined(IS_LITTLE_ENDIAN) || defined(IS_BIG_ENDIAN)
#error "prcpucfg.h byte order does not match this little-endian target"
#endif
#elif __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
#if !defined(IS_BIG_ENDIAN) || defined(IS_LITTLE_ENDIAN)
#error "prcpucfg.h byte order does not match this big-endian target"
#endif
#else
#error "unsupported byte order"
#endif

int main(void)
{
    puts("generated prcpucfg.h matches the target ABI");
    return 0;
}
