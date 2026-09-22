from __future__ import annotations
import httpx
from typing import Any

class GitHubClient:
    def __init__(self, token: str, repo: str, base_url: str="https://api.github.com"):
        self.repo=repo
        self.client=httpx.AsyncClient(base_url=base_url, headers={
            "Authorization":f"Bearer {token}","Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"})

    async def _req(self, method: str, path: str, **kwargs) -> Any:
        r=await self.client.request(method,path,**kwargs); r.raise_for_status()
        return r.json() if r.content else None

    async def get_issue(self, number:int): return await self._req("GET",f"/repos/{self.repo}/issues/{number}")
    async def comment(self, number:int, body:str): return await self._req("POST",f"/repos/{self.repo}/issues/{number}/comments",json={"body":body})
    async def set_labels(self, number:int, labels:list[str]): return await self._req("POST",f"/repos/{self.repo}/issues/{number}/labels",json={"labels":labels})
    async def close_issue(self, number:int): return await self._req("PATCH",f"/repos/{self.repo}/issues/{number}",json={"state":"closed","state_reason":"completed"})
    async def create_issue(self,title:str,body:str,labels:list[str]): return await self._req("POST",f"/repos/{self.repo}/issues",json={"title":title,"body":body,"labels":labels})
    async def permission(self, username:str)->str:
        data=await self._req("GET",f"/repos/{self.repo}/collaborators/{username}/permission")
        return data.get("permission","none")
