// 서랍 뒤로 가기 — 서랍 안에서 바뀐 화면을 "다시 그릴 수 있는 설명자"로 쌓는다. DOM에 의존하지 않는다 (node로 시험).
//
//   설명자: { kind: "item", id } · { kind: "letter", body } · { kind: "mind", req } · { kind: "catalog", group, q }
//           { kind: "explore", query } · { kind: "tonight" } · { kind: "unfold", id }
//   밑줄(_)로 시작하는 필드는 다시 그릴 때만 쓰는 덧붙임(예: 하늘에서 누른 별의 화면 데이터)이라 같은 화면인지 볼 때 빼고 비교한다.
//   스택에는 지금 화면 이전의 화면들만 쌓인다. 지금 화면은 main.js가 따로 들고 있다

export const STACK_LIMIT = 20;

// 같은 화면인지 — 필드 순서와 관계없이, 밑줄 필드는 빼고
export function viewKey(view) {
  if (!view) return "";
  return JSON.stringify(Object.keys(view).filter((k) => !k.startsWith("_")).sort().map((k) => [k, view[k] ?? null]));
}

export const sameView = (a, b) => viewKey(a) === viewKey(b);

// 화면 하나를 쌓는다 — 맨 위와 같은 화면이면 그대로, 깊이를 넘으면 가장 오래된 화면부터 버린다. 새 배열을 돌려준다
export function pushView(stack, view, limit = STACK_LIMIT) {
  if (!view) return stack;
  if (stack.length && sameView(stack[stack.length - 1], view)) return stack;
  const next = [...stack, view];
  return next.length > limit ? next.slice(next.length - limit) : next;
}

// 맨 위의 화면을 꺼낸다 — { stack, view } (비어 있으면 view는 null)
export function popView(stack) {
  if (!stack.length) return { stack, view: null };
  return { stack: stack.slice(0, -1), view: stack[stack.length - 1] };
}

// 새 화면으로 바뀔 때 — 지금 화면(current)을 스택에 올리고 next를 지금 화면으로. 같은 화면을 다시 열면 쌓지 않는다
export function advance({ stack, current }, next, limit = STACK_LIMIT) {
  if (!current || sameView(current, next)) return { stack, current: next };
  return { stack: pushView(stack, current, limit), current: next };
}
