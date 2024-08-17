import numpy as np
from collections import deque
from typing import Optional
import deeplib

class NoGrad:
    _enabled = False

    def __enter__(self):
        self.prev = NoGrad._enabled
        NoGrad._enabled = True

    def __exit__(self, exc_type, exc_value, traceback):
        NoGrad._enabled = self.prev


def no_grad():
    return NoGrad()


class Tensor:
    def __init__(self, data, _children=(), requires_grad=False, dtype=np.float32):
        if not isinstance(data, np.ndarray):
            data = np.array(data, dtype=dtype)
        self.data = data
        self.shape = self.data.shape
        self.dtype = self.data.dtype

        self.requires_grad = requires_grad and not NoGrad._enabled
        self.grad = np.zeros_like(self.data) if self.requires_grad else None
        self._backward = lambda: None
        self._children = set(_children)

    def zero_grad(self) -> None:
        if self.grad is not None:
            self.grad.fill(0)

    def backward(self) -> None:
        if not self.requires_grad:
            raise RuntimeError(
                "Cannot call backward() on a tensor that does not require gradients."
            )
        self.grad = np.ones_like(self.data)

        topo = []
        visited = set()

        def build_topo(v):
            if v not in visited:
                visited.add(v)
                for child in v._children:
                    build_topo(child)
                topo.append(v)

        build_topo(self)

        for node in reversed(topo):
            node._backward()
            
    def size(self):
        return self.data.size

    def dim(self):
        return len(self.shape)

    def item(self):
        return self.data.item()

    def normal_(self, mean=0, std=1):
        self.data = np.random.normal(mean, std, self.shape)
        return self

    def __repr__(self):
        # numpy representation
        np_str = np.array2string(
            self.data, separator=", ", precision=4, suppress_small=True
        )
        lines = np_str.split("\n")
        # add 'tensor(' at the beginning and extra spacing
        formatted_lines = ["tensor(" + lines[0]] + [
            " " * 8 + line.strip() for line in lines[1:]
        ]
        formatted_lines[-1] += ")"

        tensor_str = "\n".join(formatted_lines)
        return tensor_str + f"       dtype={self.data.dtype}, shape={self.shape}"

    def __getitem__(self, key):
        if isinstance(key, Tensor):
            key = key.data
        sliced_data = self.data[key]
        out = Tensor(sliced_data, _children=(self,), requires_grad=self.requires_grad)

        def _backward():
            if self.requires_grad:
                grad = np.zeros_like(self.data)
                grad[key] = out.grad
                self.grad += grad

        out._backward = _backward
        return out


# operators
# ----------------------------------------------
    def __add__(self, other):
        return deeplib.add(self, other)

    def __iadd__(self, other):
        return self + other

    def __radd__(self, other):
        return self + other

    def __neg__(self):
        return self * -1

    def __sub__(self, other):
        return self + (-other)

    def __mul__(self, other):
        other = (
            other if isinstance(other, Tensor) else Tensor(other, requires_grad=False)
        )

        requires_grad = self.requires_grad or other.requires_grad
        out = Tensor(
            self.data * other.data, _children=(self, other), requires_grad=requires_grad
        )

        def _backward():
            if self.requires_grad:
                grad_self = other.data * out.grad
                while grad_self.ndim > self.grad.ndim:
                    grad_self = grad_self.sum(axis=0)
                for i, dim in enumerate(self.grad.shape):
                    if dim == 1:
                        grad_self = grad_self.sum(axis=i, keepdims=True)
                self.grad = self.grad + grad_self

            if other.requires_grad:
                grad_other = self.data * out.grad
                while grad_other.ndim > other.grad.ndim:
                    grad_other = grad_other.sum(axis=0)
                for i, dim in enumerate(other.grad.shape):
                    if dim == 1:
                        grad_other = grad_other.sum(axis=i, keepdims=True)
                other.grad = other.grad + grad_other

        out._backward = _backward
        return out

    def __rmul__(self, other):
        return self * other

    def __truediv__(self, other):
        return self * other**-1

    def __matmul__(self, other):
        requires_grad = self.requires_grad or other.requires_grad
        out = Tensor(
            self.data @ other.data, _children=(self, other), requires_grad=requires_grad
        )

        def _backward():
            if self.requires_grad:
                self.grad += out.grad @ other.data.T
            if other.requires_grad:
                other.grad += self.data.T @ out.grad

        out._backward = _backward
        return out

    def __pow__(self, other):
        assert isinstance(other, (int, float))

        out = Tensor(
            self.data**other, _children=(self,), requires_grad=self.requires_grad
        )

        def _backward():
            if self.requires_grad:
                self.grad += out.grad * other * self.data ** (other - 1)

        out._backward = _backward
        return out
# ----------------------------------------------

    def gather(self, dim, index):
        # Ensure index is a Tensor
        if not isinstance(index, Tensor):
            index = Tensor(index)

        # Create a list of slice objects for indexing
        slices = [slice(None)] * self.dim()

        # Replace the slice at the specified dimension with the index array
        slices[dim] = index.data

        # Use advanced indexing to gather the values
        gathered_data = self.data[tuple(slices)]

        out = Tensor(gathered_data, _children=(self,), requires_grad=self.requires_grad)

        def _backward():
            if self.requires_grad:
                grad = np.zeros_like(self.data)
                np.add.at(grad, tuple(slices), out.grad)
                self.grad += grad

        out._backward = _backward
        return out

    def __gt__(self, other):
        assert isinstance(other, (int, float, Tensor))
        other = other if isinstance(other, Tensor) else Tensor(other)
        return Tensor(self.data > other.data, dtype=np.float32)

    def max(self, dim=None, keepdims=False):
        out = Tensor(
            np.max(self.data, axis=dim, keepdims=keepdims),
            _children=(self,),
            requires_grad=self.requires_grad,
        )

        def _backward():
            if self.requires_grad:
                self.grad += out.grad * (self.data == out.data)

        out._backward = _backward
        return out

    def exp(self):
        out = Tensor(
            np.exp(self.data), _children=(self,), requires_grad=self.requires_grad
        )

        def _backward():
            if self.requires_grad:
                self.grad += out.grad * out.data

        out._backward = _backward
        return out

    def log(self):
        out = Tensor(
            np.log(self.data), _children=(self,), requires_grad=self.requires_grad
        )

        def _backward():
            if self.requires_grad:
                self.grad += out.grad / self.data

        out._backward = _backward
        return out

    def sum(self, dim=None, keepdims=False):
        out = Tensor(
            np.sum(self.data, axis=dim, keepdims=keepdims),
            _children=(self,),
            requires_grad=self.requires_grad,
        )

        def _backward():
            if self.requires_grad:
                grad = out.grad
                # if axis is None, the gradient is scalar and should be broadcasted to the original shape
                if dim is None:
                    grad = np.ones_like(self.data) * grad
                else:
                    if not keepdims:
                        grad = np.expand_dims(grad, axis=dim)
                    grad = np.broadcast_to(grad, self.shape)
                self.grad += grad

        out._backward = _backward
        return out

    def mean(self, dim=None, keepdims=False):
        return self.sum(dim=dim, keepdims=keepdims) / self.data.size

    def var(self, dim=None, keepdims=False, unbiased=False):
        mean = self.mean(dim=dim, keepdims=True)
        squared_diff = (self - mean) ** 2

        if unbiased:
            count = self.data.size if dim is None else self.data.shape[dim]
            count -= 1
        else:
            count = self.data.size if dim is None else self.data.shape[dim]

        return squared_diff.sum(dim=dim, keepdims=keepdims) / count

    def sqrt(self):
        return self**0.5



