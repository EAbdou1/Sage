import React from 'react'
import { ModeToggle } from './mode-toggle'

export default function Header() {
  return (
    <div className="p-4 border-b flex justify-between items-center w-full">
      <div>
        <h1 className="text-2xl font-bold">SAGE AI</h1>
      </div>
      <div>
        <ModeToggle />
      </div>
    </div>
  )
}
