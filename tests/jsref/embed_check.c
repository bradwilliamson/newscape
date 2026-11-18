/*
 * Embed the js/ref engine the way any program linking the jsref CMake target
 * would: no include paths, defines or link flags beyond what the target
 * publishes. Evaluates a script and checks the result.
 */
#include "jsapi.h"

#include <stdio.h>

static JSClass global_class = {
    .name = "global",
    .flags = 0,
    .addProperty = JS_PropertyStub,
    .delProperty = JS_PropertyStub,
    .getProperty = JS_PropertyStub,
    .setProperty = JS_PropertyStub,
    .enumerate = JS_EnumerateStub,
    .resolve = JS_ResolveStub,
    .convert = JS_ConvertStub,
    .finalize = JS_FinalizeStub,
};

static void report_error(JSContext *cx, const char *message, JSErrorReport *report)
{
    (void)cx;
    fprintf(stderr, "%s:%u: %s\n", report && report->filename ? report->filename : "?",
            report ? report->lineno : 0u, message);
}

int main(void)
{
    static const char source[] = "var answer = 6; answer * 7";
    JSRuntime *rt;
    JSContext *cx;
    JSObject *global;
    jsval result;
    jsdouble number = 0;
    int ok = 0;

    rt = JS_NewRuntime(1L << 20);
    if (!rt)
        return 1;
    cx = JS_NewContext(rt, 8192);
    if (!cx) {
        JS_DestroyRuntime(rt);
        return 1;
    }
    JS_SetErrorReporter(cx, report_error);

    global = JS_NewObject(cx, &global_class, NULL, NULL);
    if (global && JS_InitStandardClasses(cx, global) &&
        JS_EvaluateScript(cx, global, source, sizeof source - 1, "embed_check", 1, &result)) {
        /*
         * Use API calls, not the JSVAL_IS_INT/JSVAL_TO_INT macros: JSVAL_IS_INT
         * expands to INT_TO_JSVAL of a negative value, a left shift of a
         * negative number, which is undefined in standard C.
         */
        ok = JS_TypeOfValue(cx, result) == JSTYPE_NUMBER &&
             JS_ValueToNumber(cx, result, &number) && number == 42.0;
        printf("embedded js/ref evaluated \"%s\" -> %g\n", source, number);
    }

    JS_DestroyContext(cx);
    JS_DestroyRuntime(rt);
    JS_ShutDown();
    return ok ? 0 : 1;
}
